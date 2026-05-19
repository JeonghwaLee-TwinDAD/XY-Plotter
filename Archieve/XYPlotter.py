import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib.widgets import Button
import pandas as pd
import numpy as np
import threading
import time
import queue

# ################################################################################################################################################################################
# Initialize key variables and test passing criteria
DATALOG_PATH = 'C:\\_Data_Log\\'               # Path to save datalogs
SUPPLY_PRESSURE = 3000
SCALE_FACTOR = {'X': 0.0025, 'Y': 1}         #Axis scaling for X and Y
STROKE = 10.0                                   # Stroke length in thousandths of an inch
FLOW_LIMIT = 16                                 # Flow limit in gpm
BUILD_PROFILE =[
        [        
            {
            "Test Mode":"Decreasing",
            "Ramp Start":10,
            "Null Upper Limit":1,
            "Null Lower Limit":-1,
            "Ramp End":-10,
            "Ramp Rate Far":2,
            "Ramp Rate Close":0.5
            },
            {
            "Test Mode":"Decreasing",
            "Ramp Start":10,
            "Null Upper Limit":1,
            "Null Lower Limit":-1,
            "Ramp End":-10,
            "Ramp Rate Far":2,
            "Ramp Rate Close":0.5
            }
        ]
    ]

# ################################################################################################################################################################################

class XYPlotter:
    """Live plotter using matplotlib animation"""

    def __init__(self, update_interval: int = 20) -> None:
        """
        Initialize XY plotter
        
        Args:
            tss: test stand system mock or real object
            update_interval: milliseconds between updates
        """
        
        self.interval = update_interval  
        
        # Configure XY Plot properties
        self.fig, self.ax = plt.subplots(figsize=(10, 5), dpi=100)
        self.fig.canvas.mpl_connect('close_event', self._on_close)
        # Listen for keypresses (F8 to toggle Start/Stop)
        self.fig.canvas.mpl_connect('key_press_event', self._on_key)
            
        plt.tight_layout()
        plt.subplots_adjust(top=0.92, bottom=0.1, left=0.1, right=0.92)  # Adjust margins for buttons and labels instead of plt.tight_layout()        
            
        self.ax.grid(False)       

        #Add a textbox
        self.part_text = self.ax.text(
            0.52, 0.98, "",
            transform=self.ax.transAxes,
            fontsize=10,
            family='monospace',
            verticalalignment='top',
            bbox=dict(boxstyle="square, pad=0.5", facecolor="white", edgecolor="white", linewidth=1)
        )
        
        self.timing_text = self.ax.text(
            0.01, 0.99, "Plot Loop: -- ms",
            transform=self.ax.transAxes,
            fontsize=8,
            family='monospace',
            verticalalignment='top',
            color='gray'
        )
        self.last_update_time = time.time()

        self.set_layout()
                                    
        # Active buffers for thread-safe polling
        self.series_data = {}
        self.lines = {}       
        self.dynamic_annotations = []
        self.is_running = False

        # Thread control & Producer-Consumer Queue
        self._stop_event = threading.Event()
        self.data_queue = queue.Queue()
        self.event_queue = queue.Queue()
        self.event_thread = threading.Thread(target=self._event_loop, daemon=True)
        self.event_thread.start()

        # Setup animation
        self.anim = FuncAnimation(
            self.fig,
            self.update_plot,
            interval=update_interval,       # delay between frames in milliseconds
            blit=False,
            cache_frame_data=False
        )              

    def _run(self, event):
        """Toggle polling on or off and reset to run again if it was stopped at the end."""
        self.is_running = not self.is_running
        if self.is_running:
            if hasattr(self, 'btn_run'):
                self.btn_run.label.set_text('Stop')
            self.event_queue.put({'cmd': 'START'})
        else:
            if hasattr(self, 'btn_run'):
                self.btn_run.label.set_text('Start')
            self.event_queue.put({'cmd': 'STOP'})
                
    def idle_state(self):
        """Set the plot to an idle state when testing concludes."""
        self.is_running = False
        if hasattr(self, 'btn_run'):
            self.btn_run.label.set_text('Start')
            self.btn_run.set_active(False)
            self.btn_run.label.set_color('grey')
        if hasattr(self, 'fig'):
            self.fig.canvas.draw_idle()
            
    def ready_state(self):
        """Set the plot to a ready state when initializing or clearing a test."""
        self.is_running = False
        if hasattr(self, 'btn_run'):
            self.btn_run.label.set_text('Start')
            self.btn_run.set_active(True)
            self.btn_run.label.set_color('black')
        if hasattr(self, 'fig'):
            self.fig.canvas.draw_idle()

    def _clear_plot(self, event=None):
        """Clear all plotted lines, annotations, and test text."""
        self.ready_state()
        self.event_queue.put({'cmd': 'RESET_INDEX'})
        self._idx_ = 0

        for k in self.series_data.keys():
            self.series_data[k] = {'X': [], 'Y': []}
            if k in self.lines:
                self.lines[k].set_data([], [])
                
        for ann in self.dynamic_annotations:
            try:
                ann.remove()
            except ValueError:
                pass
        self.dynamic_annotations.clear()
        
        with self.data_queue.mutex:
            self.data_queue.queue.clear()
            
        text = self.part_text.get_text()
        lines = text.split('\n')
        base_lines = []
        for line in lines:
            base_lines.append(line)
            if "Supply Press:" in line:
                break
        self.part_text.set_text('\n'.join(base_lines) + '\n')
        
        self.fig.canvas.draw_idle()

    def _event_loop(self):
        """
        LabVIEW-style Event Structure / Queued Message Handler.
        Uses queue.get(timeout=...) to mimic a LabVIEW Event Structure's Timeout terminal.
        This allows handling UI/system events instantly, while running cyclic polling
        only when no events are pending and the timeout elapses.
        """
        self._idx_ = 0
        
        while not self._stop_event.is_set():
            try:
                event = self.event_queue.get(timeout=self.interval / 1000.0)
                match event.get('cmd'):
                    case 'RESET_INDEX':
                        self._idx_ = 0
                    case 'START':
                        if hasattr(self, 'X_source') and self._idx_ >= len(self.X_source):
                            self._idx_ = 0
                        if getattr(self, '_idx_', 0) == 0:
                            with self.data_queue.mutex:
                                self.data_queue.queue.clear()
                    case 'STOP':
                        pass
                    case 'EXIT':
                        break
            except queue.Empty:
                # 'Timeout' Case: Perform continuous hardware/data polling here
                if self.is_running and hasattr(self, 'X_source') and self._idx_ < len(self.X_source):
                    series_id = getattr(self, 'series_id', 1)
                    self.data_queue.put((series_id, self.X_source[self._idx_], self.Y_source[self._idx_]))
                    self._idx_ += 1

    def _on_close(self, event):
        """Handle plot close event to stop polling thread"""
        self._stop_event.set()
        self.event_queue.put({'cmd': 'EXIT'})
        self.is_running = False
        if hasattr(self, 'anim') and getattr(self.anim, 'event_source', None) is not None:
            self.anim.event_source.stop()

    def _on_key(self, event):
        """Handle key press events. Press F8 to toggle Start/Stop."""
        try:
            key = event.key
        except Exception:
            return

        if key:
            k = str(key).lower()
            if k == 'f8':
                # Reuse the same toggle routine as the button
                self._run(event)
            elif k == 'f4':
                # Close the figure window (triggers close_event -> _on_close)
                try:
                    plt.close(self.fig)
                except Exception:
                    pass

    def update_plot(self, frame):
        """Consumer: Update the plot with data points accumulated in the queue"""
        current_time = time.time()
        loop_time = (current_time - self.last_update_time) * 1000
        self.last_update_time = current_time
        self.timing_text.set_text(f"Plot Loop: {loop_time:.1f} ms")

        has_new_data = False
        # Drain the queue without blocking the GUI
        while not self.data_queue.empty():
            try:
                series_id, x, y = self.data_queue.get_nowait()
                if series_id not in self.series_data:
                    self.series_data[series_id] = {'X': [], 'Y': []}
                    color = 'grey'
                    if series_id in [3, 4]:  # No Load Drift and Pressure Gain
                        new_line, = self.ax.plot([], [], marker="s", markersize=5, color=color, linewidth=0, markerfacecolor='white', markeredgecolor=color)
                    else:  # 3-way lap, 4-way lap, and Leakage
                        new_line, = self.flow_ax.plot([], [], marker="s", markersize=5, color=color, linewidth=0, markerfacecolor='white', markeredgecolor=color)
                    self.lines[series_id] = new_line
                        
                self.series_data[series_id]['X'].append(x)
                self.series_data[series_id]['Y'].append(y)
                has_new_data = True
            except queue.Empty:
                break
            
        if has_new_data:
            for sid, line in self.lines.items():
                line.set_data(self.series_data[sid]['X'], self.series_data[sid]['Y'])    
                
        # Automatically stop and reset button label if we reach the end of the simulation data
        if hasattr(self, 'X_source') and getattr(self, '_idx_', 0) >= len(self.X_source) and self.data_queue.empty() and self.is_running:
            self.idle_state()
        
        return list(self.lines.values()) + [self.part_text, self.timing_text] + self.dynamic_annotations
        
                        
    def set_layout(self):
    
        self.fig.canvas.manager.set_window_title("FlowGrind - XY Plotter")
        self.ax.set_xlabel("Spool Position(in)")                   # "Spool Position(in)"
        self.ax.set_xlim((-1*STROKE, STROKE))
        self.ax.set_xticks(np.arange(-1*STROKE, STROKE, STROKE/4))
        
        self.ax.set_ylabel("Pressure(psi)")                   
        self.ax.set_ylim((-1*SUPPLY_PRESSURE, SUPPLY_PRESSURE))
        self.ax.set_yticks(np.arange(-1*SUPPLY_PRESSURE, SUPPLY_PRESSURE, SUPPLY_PRESSURE/3))
                
        self.flow_ax = self.ax.twinx()  # Create a secondary y-axis for flow(gpm)    
        self.flow_ax.set_ylabel("Flow(gpm)")                   
        self.flow_ax.set_ylim((-1*FLOW_LIMIT, FLOW_LIMIT))
        self.flow_ax.set_yticks(np.arange(-1*FLOW_LIMIT, FLOW_LIMIT, FLOW_LIMIT/4))
        
        AreaLabels = {
            'D': (0.95, 0.9), 
            'B': (0.05, 0.9), 
            'A': (0.95, 0.1),             
            'C': (0.05, 0.1)
        }
        self.annotations = []
        # Add annotation to a point on the main line
        for i, label in enumerate(AreaLabels):
            ann = self.ax.annotate(
                label,
                xy=AreaLabels[label],
                xycoords='axes fraction',
                fontsize=14,
                fontweight='bold',
                color='lightgray',
                ha='center',
                va='center'
            )                
            self.annotations.append(ann) 
            
        # Add infinite reference lines
        self.ref_lines = [
            self.flow_ax.axhline(y=-FLOW_LIMIT*.3, color='lightgray', linestyle='--', linewidth=1),
            self.flow_ax.axhline(y=FLOW_LIMIT*.3, color='lightgray', linestyle='--', linewidth=1),
            self.flow_ax.axhline(y=-FLOW_LIMIT*.1, color='lightgray', linestyle='--', linewidth=1),
            self.flow_ax.axhline(y=FLOW_LIMIT*.1, color='lightgray', linestyle='--', linewidth=1)
        ]
        
        # Add Start/Stop button
        self.ax_btn = plt.axes([0.66, 0.93, 0.12, 0.05])
        self.btn_run = Button(self.ax_btn, 'Start')
        self.btn_run.on_clicked(self._run)
        
        # Add Clear button
        self.ax_btn_clear = plt.axes([0.8, 0.93, 0.12, 0.05])
        self.btn_clear = Button(self.ax_btn_clear, 'Clear')
        self.btn_clear.on_clicked(self._clear_plot)

    def build_profile(
        self,
        ramp_start: float,
        null_upper: float,
        null_lower: float,
        ramp_end: float,
        rate_far: float,
        rate_close: float,
        mode: str = "increasing",
        dt: float = 0.1
    ):
        """
        Build time vs setpoint profile.
        """

        time_pts = [0.0]
        values = [ramp_start]

        current = ramp_start
        t = 0.0

        def step(target, rate):
            """Ramp toward target using rate."""
            nonlocal current, t
            while True:
                diff = target - current

                if abs(diff) < 1e-6:
                    current = target
                    break

                direction = np.sign(diff)
                current += direction * rate * dt

                if (direction > 0 and current > target) or (direction < 0 and current < target):
                    current = target

                t += dt
                time_pts.append(t)
                values.append(current)

        if mode.lower() == "increasing":
            step(null_lower, rate_far)
            step(null_upper, rate_close)
            step(ramp_end, rate_far)

        elif mode.lower() == "decreasing":
            step(null_upper, rate_far)
            step(null_lower, rate_close)
            step(ramp_end, rate_far)

        else:
            raise ValueError("mode must be 'increasing' or 'decreasing'")

        return np.array(time_pts), np.array(values)    

    def hardware_interface(self):
        """Example method to demonstrate how to send commands to hardware"""
        # Example: Send command to TSS to set supply pressure
        self.tss.set_supply_pressure(SUPPLY_PRESSURE)
        self.ready_state()
        
    def simulation_interface(self, url: str, mode: int = 0) -> None:
        """Update plot with simulated data mapping to lines by valve_id."""
        # This is handled in the _poll_data method which simulates hardware data updates

        df = pd.read_csv(url, sep=",") 
                
        self.X_source = df["xname"].tolist()
        self.Y_source = df["yname"].tolist()       
        self.series_id = mode  # Use mode to differentiate lines in the plot, can be set externally before calling this method
        self.event_queue.put({'cmd': 'RESET_INDEX'})
        self._idx_ = 0
        self.ready_state()

    
'''if __name__ == '__main__':

    plotter = XYPlotter(update_interval=100)
    
    plt.show()
'''