# 2025-10-01 Kids Photo Filter


A locally runnable web application / CLI that can use a few photos of target person to filter a photo library in another directory, which contains many photos of other people (possibly classmates / colleagues).


Requirements:

- Runs locally, no installation required,  ideally just open a file to launch it

- Has a web UI so that non-technical users can operate it easily

- A UI control to select the "Photo Library" directory path, which contains many subdirectories with candid photos of people

- A UI control to specify the "Target Person", the face to filter for, by selecting a set of reference photos

- After selecting the "Target Person", display a preview of the selected reference photos

- A UI control to select the output directory path

- After confirming the preview, a button to start filtering

- The app filters photos from the "Photo Library" that match the "Target Person" based on the reference photo set

- Filtered photos are saved to the output directory preserving the original subdirectory structure

- The app displays the current processing progress (number of photos filtered vs. total) and the estimated time to completion


