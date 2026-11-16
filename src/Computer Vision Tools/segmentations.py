import cv2 as cv
import numpy as np

def mouse_event(event,x,y,params):
    if event == cv.EVENT_LBUTTONDOWN():
        print(f"Left Mouse button at coords {x},{y}")
        cv.circle(img, (x, y), 10, (0, 255, 0), -1)
    elif event == cv.EVENT_RBUTTONDOWN():
        print(f"Left Mouse button at coords {x},{y}")
        cv.circle(img, (x, y), 10, (0, 255, 0), -1)

img = np.zeros((640,640,3),dtype = np.uint8)
window_name = "SelectionWindow"
cv.namedWindow(window_name)

cv.setMouseCallback(window_name,mouse_event)

while True:
    cv.imshow(window_name,img)
    key = cv.waitKey(1) & 0xFF
    if key == 27 or key == ord('q'):
        break

cv.destroyAllWindows()