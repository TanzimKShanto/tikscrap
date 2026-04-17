import os


def rename_jpg_to_jpeg(root_folder):
    for foldername, subfolders, filenames in os.walk(root_folder):
        for filename in filenames:
            if filename.lower().endswith(".jpg"):
                old_path = os.path.join(foldername, filename)

                new_filename = filename[:-4] + ".jpeg"
                new_path = os.path.join(foldername, new_filename)

                # Avoid overwriting existing files
                if not os.path.exists(new_path):
                    os.rename(old_path, new_path)
                    print(f"Renamed: {old_path} -> {new_path}")
                else:
                    print(f"Skipped (already exists): {new_path}")


# Usage
rename_jpg_to_jpeg("images")
