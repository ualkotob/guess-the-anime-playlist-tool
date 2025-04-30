import tkinter as tk
import pyperclip

class RectangleDrawer:
    def __init__(self, root):
        self.root = root
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-alpha", 0.3)  # Set transparency
        self.root.configure(cursor="cross")
        
        self.canvas = tk.Canvas(root, bg="black")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        
        self.start_x = None
        self.start_y = None
        self.rect = None
        
        self.screen_width = self.root.winfo_screenwidth()
        self.screen_height = self.root.winfo_screenheight()
        
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.root.bind("<Escape>", lambda e: self.root.quit())
    
    def on_press(self, event):
        self.start_x, self.start_y = event.x, event.y
        self.rect = self.canvas.create_rectangle(self.start_x, self.start_y, event.x, event.y, outline="red", width=2)
    
    def on_drag(self, event):
        self.canvas.coords(self.rect, self.start_x, self.start_y, event.x, event.y)
    
    def on_release(self, event):
        end_x, end_y = event.x, event.y
        width = abs(end_x - self.start_x)
        height = abs(end_y - self.start_y)
        
        left_edge = min(self.start_x, end_x)
        top_edge = min(self.start_y, end_y)
        
        x_percent = (left_edge / (self.screen_width - width)) * 100
        y_percent = (top_edge / (self.screen_height - height)) * 100
        
        x_percent = edge_round(x_percent)
        y_percent = edge_round(y_percent)

        width_percent = width / self.screen_width * 100
        height_percent = height / self.screen_height * 100

        width_percent = edge_round(width_percent)
        height_percent = edge_round(height_percent)
        
        result = f"{width_percent:.2f}x{height_percent:.2f},{x_percent:.2f}x{y_percent:.2f}"
        pyperclip.copy(result)
        print(result)
        self.root.quit()

def edge_round(position):
    if position < 1:
        return 0
    elif position > 99:
        return 100
    return position

if __name__ == "__main__":
    root = tk.Tk()
    app = RectangleDrawer(root)
    root.mainloop()
