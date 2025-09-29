from ultralytics import YOLO
import cv2
import os
from huggingface_hub import hf_hub_download

# Download the model from Hugging Face
repo_id = 'foduucom/stockmarket-pattern-detection-yolov8'
model_filename = 'model.pt'  # Adjust if the filename differs (check Hugging Face repo)
model_path = hf_hub_download(repo_id=repo_id, filename=model_filename, local_dir='models')

# Load the pre-trained model
try:
    model = YOLO(model_path, task='detect')
except Exception as e:
    print(f"Error loading model: {e}")
    exit()

# Load your chart image (replace with your actual path)
image_path = './web_ui.png'  # Ensure this file exists

# Verify image exists
if not os.path.exists(image_path):
    print(f"Image not found: {image_path}")
    exit()

# Run inference with confidence and IoU thresholds to avoid overlapping patterns
results = model.predict(image_path, conf=0.7, iou=0.5)

# Print detected patterns
for box in results[0].boxes:
    if box.conf > 0.1:
        label = model.names[int(box.cls)]
        coords = box.xyxy[0].tolist()
        print(f"Pattern: {label}, Confidence: {box.conf:.2f}, Coordinates: {coords}")

# Visualize results
img = cv2.imread(image_path)
for box in results[0].boxes:
    if box.conf > 0.7:
        x1, y1, x2, y2 = map(int, box.xyxy[0])
        label = model.names[int(box.cls)]
        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(img, f"{label} {box.conf:.2f}", (x1, y1-10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
cv2.imwrite('output_chart.png', img)
print("Output saved as output_chart.png")