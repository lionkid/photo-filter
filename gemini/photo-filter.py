import os
import cv2
import numpy as np
import shutil
from pathlib import Path
from tqdm import tqdm
import insightface
from insightface.app import FaceAnalysis

# ================= CONFIGURATION =================
CONFIG = {
    # Directory containing ONLY photos of your child (Masked & Unmasked mixed is best)
    # 這是您提供的「只有孩子照片」的目錄
    "reference_dir": "/Users/kylehsieh/Pictures/Upload/謝昀宸_裕德照片集",

    # The root directory of the kindergarten photo collection
    # 幼兒園原始照片集目錄
    "source_dir": "/Users/kylehsieh/Pictures/Upload/Max/",

    # Where to save the filtered photos
    # 過濾後的照片存放目錄 (程式會自動建立)
    "output_dir": "/Users/kylehsieh/Pictures/Upload/謝昀宸_裕德照片集_filtered_0.55",

    # Similarity Threshold (0.0 to 1.0)
    # Lower value = Higher Recall (More photos, more false positives)
    # Higher value = Higher Precision (Fewer photos, less mistakes)
    # Since you want "High Recall", 0.40 is a good starting point for masked faces.
    # 建議值：0.4 (寧可錯殺)，若雜訊太多可調高至 0.45 或 0.5
    "threshold": 0.55,

    # Supported image extensions
    "extensions": ('.jpg', '.jpeg', '.png', '.bmp', '.heic')
    ,
    # Debug logging (prints reference faces, matches, and similarity info)
    "debug": False
}
# =================================================

class PhotoFilter:
    def __init__(self, config):
        self.config = config
        print("Initializing Face Analysis Model (InsightFace)...")
        # ctx_id=0 uses GPU, ctx_id=-1 uses CPU.
        # On Mac M2, CPU is fast enough and easier to set up than Metal/CoreML providers for this script.
        self.app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
        self.app.prepare(ctx_id=-1, det_size=(640, 640))
        self.target_embedding = None

    def log(self, message):
        if self.config.get("debug"):
            print(message)

    def get_embedding(self, img_path):
        """
        Reads an image and returns the embedding of the largest face found.
        """
        try:
            img = cv2.imread(img_path)
            if img is None:
                self.log(f"[REF] Unreadable image (cv2.imread returned None): {img_path}")
                return None
            
            faces = self.app.get(img)
            if not faces:
                self.log(f"[REF] No face detected: {img_path}")
                return None
            
            # If multiple faces are in the reference photo, pick the largest one (presumably the child)
            # Sort by bounding box area (width * height)
            faces = sorted(faces, key=lambda x: (x.bbox[2]-x.bbox[0]) * (x.bbox[3]-x.bbox[1]), reverse=True)
            return faces[0].embedding
        except Exception as e:
            self.log(f"[REF] Error processing {img_path}: {e}")
            return None

    def build_reference_profile(self):
        """
        Scans the reference directory to build a mean embedding vector for the child.
        """
        print(f"\nBuilding reference profile from: {self.config['reference_dir']}")
        embeddings = []
        ref_images = [f for f in os.listdir(self.config['reference_dir']) 
                      if f.lower().endswith(self.config['extensions'])]

        if not ref_images:
            raise ValueError("No images found in reference directory!")

        for fname in tqdm(ref_images, desc="Analyzing Reference Photos"):
            path = os.path.join(self.config['reference_dir'], fname)
            emb = self.get_embedding(path)
            if emb is not None:
                embeddings.append(emb)
                self.log(f"[REF] Face detected: {path}")

        if not embeddings:
            raise ValueError("No faces detected in reference photos! Please use clearer photos.")

        # Calculate the average (mean) vector of the child's face
        # This helps combine features from masked and unmasked photos
        mean_emb = np.mean(embeddings, axis=0)
        
        # Normalize the feature vector (Required for Cosine Similarity)
        self.target_embedding = mean_emb / np.linalg.norm(mean_emb)
        print(f"Reference profile built using {len(embeddings)} valid faces.")

    def process_photos(self):
        """
        Main loop to scan, compare, and copy photos.
        """
        print(f"\nScanning source directory: {self.config['source_dir']}")
        
        # 1. Collect all image files first to establish total count
        image_files = []
        for root, dirs, files in os.walk(self.config['source_dir']):
            for file in files:
                if file.lower().endswith(self.config['extensions']):
                    image_files.append(os.path.join(root, file))

        total_files = len(image_files)
        print(f"Total images found: {total_files}")
        
        found_count = 0
        
        # 2. Process with Progress Bar
        for img_path in tqdm(image_files, desc="Processing Images", unit="img"):
            try:
                img = cv2.imread(img_path)
                if img is None:
                    self.log(f"[SRC] Unreadable image (cv2.imread returned None): {img_path}")
                    continue

                faces = self.app.get(img)
                is_match = False
                best_sim = None
                best_face_idx = None
                
                # Check every face in the photo
                for idx, face in enumerate(faces):
                    # Calculate Cosine Similarity
                    # Sim = (A . B) / (||A|| * ||B||) -> embeddings are normalized, so just dot product
                    face_emb = face.embedding / np.linalg.norm(face.embedding)
                    sim = float(np.dot(face_emb, self.target_embedding))
                    if best_sim is None or sim > best_sim:
                        best_sim = sim
                        best_face_idx = idx
                    
                    if sim > self.config['threshold']:
                        is_match = True
                        break # Found the child, no need to check other faces in this photo

                if is_match:
                    dist = 1.0 - best_sim if best_sim is not None else None
                    if dist is not None:
                        print(f"[MATCH] {img_path} face#{best_face_idx} sim={best_sim:.4f} dist={dist:.4f}")
                    else:
                        print(f"[MATCH] {img_path} face#? sim=N/A dist=N/A")
                    self.copy_file(img_path)
                    found_count += 1
                else:
                    if best_sim is None:
                        self.log(f"[SRC] No face detected: {img_path}")
                    else:
                        dist = 1.0 - best_sim
                        self.log(f"[SRC] No match: {img_path} best_face#{best_face_idx} sim={best_sim:.4f} dist={dist:.4f}")
            
            except Exception as e:
                # Silently fail on bad images to keep the loop running
                self.log(f"[SRC] Error processing {img_path}: {e}")
                continue

        print(f"\n========================================")
        print(f"Processing Complete!")
        print(f"Total Scanned: {total_files}")
        print(f"Photos Found & Copied: {found_count}")
        print(f"Saved to: {self.config['output_dir']}")
        print(f"========================================")

    def copy_file(self, src_path):
        """
        Copies the file while preserving the subdirectory structure.
        """
        # Ensure output root exists
        os.makedirs(self.config['output_dir'], exist_ok=True)
        # Get relative path from source root (e.g., "2021_Fall/Event_A/img.jpg")
        rel_path = os.path.relpath(src_path, start=self.config['source_dir'])
        
        # Construct destination path
        dest_path = os.path.join(self.config['output_dir'], rel_path)
        
        # Create parent directories if they don't exist
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        
        # Copy file with metadata
        shutil.copy2(src_path, dest_path)

if __name__ == "__main__":
    # Check if paths exist
    if not os.path.exists(CONFIG['reference_dir']):
        print("Error: Reference directory does not exist.")
    elif not os.path.exists(CONFIG['source_dir']):
        print("Error: Source directory does not exist.")
    else:
        # Create output dir if not exists
        if not os.path.exists(CONFIG['output_dir']):
            os.makedirs(CONFIG['output_dir'])

        processor = PhotoFilter(CONFIG)
        processor.build_reference_profile()
        processor.process_photos()
