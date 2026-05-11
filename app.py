import threading
from pathlib import Path

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.clock import Clock
from kivy.core.window import Window

# Set background to a dark color
Window.clearcolor = (0.1, 0.1, 0.1, 1)

import main  # Import your existing main script

class StockScannerApp(App):
    def build(self):
        self.layout = BoxLayout(orientation='vertical', padding=20, spacing=20)
        
        # Header label
        self.header = Label(
            text="Swing Trading Scanner",
            font_size=32,
            size_hint=(1, 0.1),
            color=(0.9, 0.9, 0.9, 1),
            bold=True
        )
        self.layout.add_widget(self.header)

        # Status/Results Label wrapped in a ScrollView
        self.scroll = ScrollView(size_hint=(1, 0.7))
        self.result_label = Label(
            text="Press 'Run Scan' to start...",
            font_size=16,
            size_hint_y=None,
            color=(0.8, 0.8, 0.8, 1),
            halign='left',
            valign='top'
        )
        self.result_label.bind(width=lambda *x: self.result_label.setter('text_size')(self.result_label, (self.result_label.width, None)))
        self.result_label.bind(texture_size=self.result_label.setter('size'))
        self.scroll.add_widget(self.result_label)
        self.layout.add_widget(self.scroll)

        # Run Button
        self.btn = Button(
            text="Run Scan Now",
            font_size=24,
            size_hint=(1, 0.2),
            background_color=(0.2, 0.6, 1, 1),
            bold=True
        )
        self.btn.bind(on_press=self.start_scan)
        self.layout.add_widget(self.btn)

        return self.layout

    def start_scan(self, instance):
        self.btn.disabled = True
        self.btn.text = "Scanning... Please wait"
        self.result_label.text = "Starting scan. Downloading data from Chartink and Yahoo Finance...\nThis usually takes a minute or two."
        
        # Run the heavy scan in a separate thread so UI doesn't freeze
        threading.Thread(target=self.run_backend, daemon=True).start()

    def run_backend(self):
        try:
            # We run with dry=True by default to avoid sending WhatsApp messages during test runs on phone
            # Unless you want it to send WhatsApp on every button press. We'll set dry=False so it acts normally.
            main.run_once(dry=False)
            
            # Read the output from the text file
            txt_path = Path("stock_picks.txt")
            if txt_path.exists():
                output = txt_path.read_text(encoding="utf-8")
            else:
                output = "Scan finished, but no stock_picks.txt was found."
                
            # Update UI on main thread
            Clock.schedule_once(lambda dt: self.update_results(output))
            
        except Exception as e:
            error_msg = f"An error occurred:\n{str(e)}"
            Clock.schedule_once(lambda dt: self.update_results(error_msg))

    def update_results(self, text):
        self.result_label.text = text
        self.btn.disabled = False
        self.btn.text = "Run Scan Now"

if __name__ == '__main__':
    StockScannerApp().run()
