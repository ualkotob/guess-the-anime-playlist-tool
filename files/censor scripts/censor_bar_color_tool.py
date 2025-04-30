import tkinter as tk
import pyperclip
import pyautogui

class ColorPicker:
    def __init__(self, root):
        self.root = root
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-alpha", 0.3)  # Transparent
        self.root.configure(cursor="cross", bg="black")
        
        self.screen_width = self.root.winfo_screenwidth()
        self.screen_height = self.root.winfo_screenheight()
        
        self.root.bind("<Button-1>", self.on_click)  # Left click
        self.root.bind("<Escape>", lambda e: self.root.quit())  # Escape to exit

    def on_click(self, event):
        # Hide the overlay so we can get the real screen color
        self.root.attributes("-alpha", 0.0)
        self.root.update()
        
        # Take a screenshot and get pixel color at mouse position
        pixel_color = pyautogui.screenshot().getpixel((event.x_root, event.y_root))
        hex_color = '#{:02X}{:02X}{:02X}'.format(*pixel_color)
        
        pyperclip.copy(hex_color)
        print(f"Color {hex_color} copied to clipboard!")
        
        self.root.after(300, self.root.quit)  # Wait briefly then quit

if __name__ == "__main__":
    root = tk.Tk()
    app = ColorPicker(root)
    root.mainloop()
