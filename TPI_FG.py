from math import inf
import time
from unittest import case
import numpy as np
from XYPlotter import XYPlotter, SCALE_FACTOR, STROKE, FLOW_LIMIT, SUPPLY_PRESSURE, DATALOG_PATH
import matplotlib.pyplot as plt
from matplotlib.path import Path
from scipy.interpolate import interp1d
import pandas as pd
import os


# ################################################################################################################################################################################
# Initialize key variables and test passing criteria
SIMULATION = True                   # Set to True to enable simulation mode (no hardware interaction)
PART_NUMBER = '28010712-105'        # Spool / Sleeve part number
TEST_STAND_NUMBER = 'FGV2-001'      # Test stand number to be displayed on plots and datalogs
LAP_CONDITION = 0.00034             # Lap condition in inches of overlap (3-way C1 and C2)
OVERLAP_CONDITION = 0.3             # 3 way C1 overlap upper bound
SUPPLY_PRESSURE_TOLERANCE = 25
LAB_DISPLACEMENT_MAX= 0.0006        # dS Upper bound for lab testing, this is not a pass/fail criteria but rather a warning threshold to indicate potential issues with the test setup or the part being tested, such as excessive wear or damage
LAB_DISPLACEMENT_MIN= 0.0003        # dS Lower bound for new parts, this is not a pass/fail criteria but rather a warning threshold to indicate potential issues with the test setup or the part being tested, such as excessive wear or damage 
NO_LOAD_DRIFT_MAX = 850             # No load drift upper bound
NO_LOAD_DRIFT_MIN = 150             # No load drift lower bound
LEAKAGE_MAX = 0.04                  # Leakage upper bound
PRESSURE_GAIN_MIN = 4200            # Pressure gain lower bound
NEUTRAL_PRESSURE_MAX = 2500         # Neutral pressure upper bound
NEUTRAL_PRESSURE_MIN = 1000         # Neutral pressure lower bound
# ################################################################################################################################################################################

class TPI:
    # Initialization of TPI. At a minimum should send list of test points.

    def __init__(self) -> None:
        
        self.xyplotter = XYPlotter(update_interval=10)

        self.xyplotter.btn_run.on_clicked(self.restart_test)
        self.xyplotter.fig.canvas.mpl_connect('close_event', self.on_close)
        
        self.supply_press = SUPPLY_PRESSURE
        
        self.test_id = 0  # 3way 1st, This will be used to keep track of which valve configuration is currently being tested, and therefore which data series corresponds to which test point
        
        self.text_box = (
        f"P/N: {PART_NUMBER}\n"
        f"DATE : {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        self.xyplotter.part_text.set_text(self.text_box)
            
    def restart_test(self, event):
        """Callback to restart testExecution when the start button is clicked."""
        if self.xyplotter.is_running and not getattr(self, '_is_executing', False):
            self.xyplotter._clear_plot()
            if getattr(self, 'test_id', 0) >= 2:
                self.testExecution(2)
                self.testExecution(3)
                self.testExecution(4)
                self.testExecution(5)   
            else:
                self.testExecution(0)
                self.testExecution(1)

    def on_close(self, event):
        """Callback to run postUUT when the matplotlib window is closed."""
        if not getattr(self, '_is_switching_windows', False):
            self.postUUT()

    def startup(self) -> None: 
        pass

    def preUUT(self) -> None:
        pass

    def testExecution(self, test_id:int):
        '''
            This function is used to execute the test sequence for each test point. It calls the valve_state function to set the valve positions and then calls the sweep function to process and display the results.
        '''
        self.test_id = test_id
        self._is_executing = True
        try:
            if self.test_id == 0:
                self.valve_state("3way-C1")
            elif self.test_id == 1:
                self.valve_state("3way-C2")
            elif self.test_id == 2:
                self.valve_state("4wayLap")
            elif self.test_id == 3:
                self.valve_state("NoLoad")
            elif self.test_id == 4:
                self.valve_state("PG")
            elif self.test_id == 5:
                self.valve_state("Leak")
        finally:
            self._is_executing = False
            
    def postUUT(self) -> None:
        pass

    def valve_state(self, mode: str) -> None:
        '''
            This function is used to set the valve positions.
            The valve states are based on the "valve-table" mode table in the HAL.
        '''        
        configs = {
            "3way-C1": {"sim_file": "./Simulation Files/3way_AB.csv", "test_id": 0, "title": "FlowGrind - 3way Lap"},
            "3way-C2": {"sim_file": "./Simulation Files/3way_CD.csv", "test_id": 1, "title": "FlowGrind - 3way Lap"},
            "4wayLap": {"sim_file": "./Simulation Files/4way_AB.csv", "test_id": 2, "title": "FlowGrind - 4way Lap"},
            "NoLoad":  {"sim_file": "./Simulation Files/NoLoad.csv", "test_id": 3, "title": "FlowGrind - No Load Drift"},
            "PG":      {"sim_file": "./Simulation Files/PG.csv", "test_id": 4, "title": "FlowGrind - Pressure Gain"},
            "Leak":    {"sim_file": "./Simulation Files/Leak.csv", "test_id": 5, "title": "FlowGrind - Leakage"},
        }
        
        if mode not in configs:
            return

        config = configs[mode]
        
        # Update window title
        self.xyplotter.fig.canvas.manager.set_window_title(config["title"])

        if SIMULATION:
            self.xyplotter.simulation_interface(config["sim_file"], config["test_id"])
            if mode == "3way-C2":
                self.xyplotter._run(None)
            # Wait for all simulated data to be queued and plotted before proceeding
            while (getattr(self.xyplotter, '_idx_', 0) < len(getattr(self.xyplotter, 'X_source', [])) or not self.xyplotter.data_queue.empty()) and not self.xyplotter._stop_event.is_set():
                plt.pause(0.1)
        else:
            pass

        self.sweep(config["test_id"], mode)
        
        # Ensure the run button is set back to 'Start' after the test completes
        self.xyplotter.idle_state()

    def lap_Test(self, test_id):
        """
        Calculate lap distance from plotted data without plotting.
        """
        # Mask polygon (ROI boundary)
        mask_xy_up = np.array([
            [-STROKE, FLOW_LIMIT * 0.1],
            [STROKE, FLOW_LIMIT * 0.1],
            [STROKE, FLOW_LIMIT * 0.3],
            [-STROKE, FLOW_LIMIT * 0.3]
        ])  # NOT required to be closed

        mask_xy_down = np.array([
            [-STROKE, -FLOW_LIMIT * 0.1],
            [STROKE, -FLOW_LIMIT * 0.1],
            [STROKE, -FLOW_LIMIT * 0.3],
            [-STROKE, -FLOW_LIMIT * 0.3]
        ])

        # ---------------------------
        # Create polygon path
        # ---------------------------
        polygon_up = Path(mask_xy_up)
        polygon_down = Path(mask_xy_down)

        data_xy = self.process_plotted_data(test_id)
        if data_xy is None:
            return None, None
            
        inside_mask_up = polygon_up.contains_points(data_xy)
        inside_mask_down = polygon_down.contains_points(data_xy)
        
        masked_data_up = data_xy[inside_mask_up]
        masked_data_down = data_xy[inside_mask_down]

        # Visually highlight the upper masked data on the plot (blue)
        if len(masked_data_up) > 0:
            mask_line_up, = self.xyplotter.flow_ax.plot(
                masked_data_up[:, 0], masked_data_up[:, 1], 
                marker="o", markersize=5, color='blue', linewidth=0, 
                markerfacecolor='white', markeredgecolor='blue'
            )
            self.xyplotter.series_data[f"mask_up_{test_id}"] = {'X': masked_data_up[:, 0].tolist(), 'Y': masked_data_up[:, 1].tolist()}
            self.xyplotter.lines[f"mask_up_{test_id}"] = mask_line_up

        # Visually highlight the lower masked data on the plot (red)
        if len(masked_data_down) > 0:
            mask_line_down, = self.xyplotter.flow_ax.plot(
                masked_data_down[:, 0], masked_data_down[:, 1], 
                marker="s", markersize=5, color='red', linewidth=0, 
                markerfacecolor='white', markeredgecolor='red'
            )
            self.xyplotter.series_data[f"mask_down_{test_id}"] = {'X': masked_data_down[:, 0].tolist(), 'Y': masked_data_down[:, 1].tolist()}
            self.xyplotter.lines[f"mask_down_{test_id}"] = mask_line_down

        x_int_up = None
        if len(masked_data_up) > 1:
            x_up = masked_data_up[:, 0]
            y_up = masked_data_up[:, 1]
            m_up, b_up = np.polyfit(x_up, y_up, 1)
            
            x_int_up = -b_up / m_up if m_up != 0 else None
            if x_int_up is not None:
                x_line_up = np.array([min(x_up.min(), x_int_up), max(x_up.max(), x_int_up)])
                y_line_up = m_up * x_line_up + b_up
                up_line, = self.xyplotter.flow_ax.plot(x_line_up, y_line_up, color='black', linestyle='--')
                self.xyplotter.series_data[f"fit_up_{test_id}"] = {'X': x_line_up.tolist(), 'Y': y_line_up.tolist()}
                self.xyplotter.lines[f"fit_up_{test_id}"] = up_line

                # Plot the upper x-intercept point
                int_pt_up, = self.xyplotter.flow_ax.plot([x_int_up], [0], marker="o", color="blue", markersize=8, linestyle="None")
                self.xyplotter.series_data[f"int_up_{test_id}"] = {'X': [x_int_up], 'Y': [0.0]}
                self.xyplotter.lines[f"int_up_{test_id}"] = int_pt_up

        x_int_down = None
        if len(masked_data_down) > 1:
            x_down = masked_data_down[:, 0]
            y_down = masked_data_down[:, 1]
            m_down, b_down = np.polyfit(x_down, y_down, 1)
            
            x_int_down = -b_down / m_down if m_down != 0 else None
            if x_int_down is not None:
                x_line_down = np.array([min(x_down.min(), x_int_down), max(x_down.max(), x_int_down)])
                y_line_down = m_down * x_line_down + b_down
                down_line, = self.xyplotter.flow_ax.plot(x_line_down, y_line_down, color='black', linestyle='--')
                self.xyplotter.series_data[f"fit_down_{test_id}"] = {'X': x_line_down.tolist(), 'Y': y_line_down.tolist()}
                self.xyplotter.lines[f"fit_down_{test_id}"] = down_line

                # Plot the lower x-intercept point
                int_pt_down, = self.xyplotter.flow_ax.plot([x_int_down], [0], marker="s", color="red", markersize=8, linestyle="None")
                self.xyplotter.series_data[f"int_down_{test_id}"] = {'X': [x_int_down], 'Y': [0.0]}
                self.xyplotter.lines[f"int_down_{test_id}"] = int_pt_down

        if x_int_up is not None:
            x_int_up *= SCALE_FACTOR['X']
        if x_int_down is not None:
            x_int_down *= SCALE_FACTOR['X']

        return x_int_up, x_int_down

    def process_plotted_data(self, test_id: int):
        # 1. Fetch the data dictionary for the specific test run
        data_dict = self.xyplotter.series_data.get(test_id)
        
        # 2. Safely check if data exists
        if not data_dict or not data_dict['X']:
            print(f"No plotting data found for valve ID {test_id}.")
            return None
            
        # 3. Extract X and Y lists
        x_values = data_dict['X']
        y_values = data_dict['Y']
        
        # 4. Optionally, stack them into a 2D numpy array for easy mathematical processing
        data_xy = np.column_stack((x_values, y_values))
        
        # 5. Remove any row with NaN values
        valid_mask = ~np.isnan(data_xy).any(axis=1)
        data_xy = data_xy[valid_mask]
        if len(data_xy) == 0:
            return None
            
        #print(f"Successfully retrieved {len(data_xy)} valid data points.")
        return data_xy
        
    def sweep(self, test_id: int, mode: str):
        """
        Process and display results for sweeps.
        """
        data_xy = self.process_plotted_data(test_id)
        if data_xy is None:
            return
            
        x_data = data_xy[:, 0]
        y_data = data_xy[:, 1]
        max_val = np.max(y_data)
        min_val = np.min(y_data)
        
        sweep_text = ""
        
        match mode:
            case ("3way-C1" | "3way-C2" | "4wayLap"):
                x_up, x_down = self.lap_Test(test_id)
                if not hasattr(self, 'x_intercepts'):
                    self.x_intercepts = {}
                if x_up is not None:
                    self.x_intercepts[f"{test_id}_up"] = x_up
                if x_down is not None:
                    self.x_intercepts[f"{test_id}_down"] = x_down

                # Only calculate and plot annotations after the 2nd 3-way sweep completes
                if mode == "3way-C2":
                    if len(self.x_intercepts) >= 4 and "0_up" in self.x_intercepts and "1_up" in self.x_intercepts:
                        dist_up = abs(self.x_intercepts["0_up"] - self.x_intercepts["1_up"])
                        dist_down = abs(self.x_intercepts["0_down"] - self.x_intercepts["1_down"])
                        
                        sweep_text = (            
                            f"Lap Condition: {LAP_CONDITION:g} Overlap\n" 
                            f"X Scale: {SCALE_FACTOR['X']:g} in/rev, Y Scale: {SCALE_FACTOR['Y']:g} gpm/Hz\n"
                            f"Blue (Up) Lap dS: {dist_up:.3g} in\n"
                            f"Red (Down) Lap dS: {dist_down:.3g} in"
                        )
                if mode == "4wayLap":
                    if "2_up" in self.x_intercepts and "2_down" in self.x_intercepts:
                        dist = abs(self.x_intercepts["2_up"] - self.x_intercepts["2_down"])
                        
                        Lab_Result = "PASS" if LAB_DISPLACEMENT_MIN <= dist <= LAB_DISPLACEMENT_MAX else "FAIL"
                        sweep_text = (f"Lap Distance: {LAP_CONDITION} O/L @ {dist:.3g} in, {Lab_Result}")
                        
                        # Compute unscaled midpoint for plotting on the unscaled x-axis
                        mid_x_unscaled = ((self.x_intercepts["2_up"] + self.x_intercepts["2_down"]) / 2) / SCALE_FACTOR['X']
                        
                        ann_lap = self.xyplotter.flow_ax.annotate(
                            f"4Way Lap Distance : {dist:.3g} in", xy=(mid_x_unscaled, 0), xytext=(-10, 40),
                            textcoords="offset points", ha='center', va='bottom', color='black',
                            arrowprops=dict(arrowstyle="->", color='black')
                        )
                        ann_lap.series_id = test_id
                        self.xyplotter.dynamic_annotations.extend([ann_lap])
                        
            case "NoLoad":
                valid_mask = (x_data >= -STROKE) & (x_data <= STROKE)
                x_valid = x_data[valid_mask]
                y_valid = y_data[valid_mask]

                if len(y_valid) > 0:
                    max_val = np.max(y_valid)
                    min_val = np.min(y_valid)
                    x_max = x_valid[np.argmax(y_valid)]
                    x_min = x_valid[np.argmin(y_valid)]
                else:
                    x_max = x_data[np.argmax(y_data)]
                    x_min = x_data[np.argmin(y_data)]
                
                NoLoad_Max_Result = "PASS" if NO_LOAD_DRIFT_MAX <= (self.supply_press*0.5 + max_val) else "FAIL"
                NoLoad_Min_Result = "PASS" if NO_LOAD_DRIFT_MIN <= (self.supply_press*0.5 + min_val) else "FAIL"

                # Annotate min/max point
                ann_max = self.xyplotter.ax.annotate(
                    f"Max. No Load Drift : {int(self.supply_press*0.5 + max_val)} psi, {NoLoad_Max_Result}", xy=(x_max, max_val), xytext=(30, 30),
                    textcoords="offset points", ha='center', va='bottom', color='red',
                    arrowprops=dict(arrowstyle="->", color='red')
                )
                ann_min = self.xyplotter.ax.annotate(
                    f"Min. No Load Drift : {int(self.supply_press*0.5 + min_val)} psi, {NoLoad_Min_Result}", xy=(x_min, min_val), xytext=(-30, -30),
                    textcoords="offset points", ha='center', va='top', color='blue',
                    arrowprops=dict(arrowstyle="->", color='blue'),
                )
                ann_max.series_id = test_id
                ann_min.series_id = test_id
                
                self.xyplotter.dynamic_annotations.extend([ann_max,ann_min])

            case "PG":
                # Find Pressure Gain slope between -40% and 40% of supply pressure
                y_target_min = -0.4 * self.supply_press
                y_target_max = 0.4 * self.supply_press
                
                x_scale = 0.05  # Update X scale factor for PG test to convert from encoder counts to thousandths of an inch (thou)           
                
                sorted_indices = np.argsort(y_data)
                x_sorted = x_data[sorted_indices]
                y_sorted = y_data[sorted_indices]
                x_sorted_scaled = x_sorted * x_scale
                            
                interpolate_function = interp1d(y_sorted, x_sorted, kind='linear', fill_value="extrapolate")
                interpolate_function_scaled = interp1d(y_sorted, x_sorted_scaled, kind='linear', fill_value="extrapolate")
                
                x_min_interp = interpolate_function(y_target_min)
                x_max_interp = interpolate_function(y_target_max)
                
                x_min_scaled = interpolate_function_scaled(y_target_min)
                x_max_scaled = interpolate_function_scaled(y_target_max)
                
                slope = (y_target_max - y_target_min) / (x_max_scaled - x_min_scaled) if (x_max_scaled - x_min_scaled) != 0 else 0        
                sweep_text = (f"PG Slope: {abs(slope/1000):.2g} psi/thou, {'PASS' if (abs(slope) >= PRESSURE_GAIN_MIN) else 'FAIL'}\n")  # Convert slope to psi/thou for display
                
                # Plot the slope line on ax
                pg_line, = self.xyplotter.ax.plot([x_min_interp, x_max_interp], [y_target_min, y_target_max], color='green', linestyle='-', linewidth=3)
                self.xyplotter.series_data[f"pg_slope_{test_id}"] = {'X': [float(x_min_interp), float(x_max_interp)], 'Y': [float(y_target_min), float(y_target_max)]}
                self.xyplotter.lines[f"pg_slope_{test_id}"] = pg_line
                
                # Annotate the PG slope at the midpoint of the line
                mid_x = float((x_min_interp + x_max_interp) / 2)
                mid_y = float((y_target_min + y_target_max) / 2)
                
                ann_pg = self.xyplotter.ax.annotate(
                    f"PG Slope: {abs(slope/1000):.2g} psi/thou", xy=(mid_x, mid_y), xytext=(30, 10),
                    textcoords="offset points", ha='left', va='top', color='green',
                    arrowprops=dict(arrowstyle="->", color='green')
                )
                ann_pg.series_id = test_id
                self.xyplotter.dynamic_annotations.extend([ann_pg])
                
            case "Leak":
                valid_mask = (x_data >= -STROKE) & (x_data <= STROKE)
                x_valid = x_data[valid_mask]
                y_valid = y_data[valid_mask]

                if len(y_valid) > 0:
                    max_val = np.max(y_valid)
                    min_val = np.min(y_valid)
                    x_max = x_valid[np.argmax(y_valid)]
                else:
                    x_max = x_data[np.argmax(y_data)]

                max_leak = abs(max_val - min_val)
                sweep_text = (f"Max Leakage: {max_leak:.2g} gpm, {'PASS' if max_leak <= LEAKAGE_MAX else 'FAIL'}")

                # Annotate max leakage point
                ann_leak = self.xyplotter.flow_ax.annotate(
                    f"Max Leakage: {max_leak:g} gpm", xy=(x_max, max_val), xytext=(0, 20),
                    textcoords="offset points", ha='center', va='bottom', color='purple',
                    arrowprops=dict(arrowstyle="->", color='purple')
                )
                ann_leak.series_id = test_id
                self.xyplotter.dynamic_annotations.extend([ann_leak])

        if sweep_text:
            formatted_text = sweep_text.strip() + "\n"
            #print(formatted_text)
            
            if mode in ("3way-C1", "3way-C2"):
                temp_text = self.text_box + formatted_text
                self.xyplotter.part_text.set_text(temp_text)
            else:
                self.text_box += formatted_text
                temp_text = self.text_box + f'Test Stand Number: {TEST_STAND_NUMBER}, Operator:          '
                self.xyplotter.part_text.set_text(temp_text)

    def logdata(self):
        data_to_export = {}
        max_len = 0
        
        test_id_map = {
            2: "4wayLap",
            3: "NoLoad",
            4: "PG",
            5: "Leak"
        }
        
        for key, data_dict in self.xyplotter.series_data.items():
            # Only include 4-way, No Load, PG, and Leakage raw test data (valve IDs 2, 3, 4, 5).
            # This explicitly excludes 3-way data (0, 1) and any overlay strings (masks, slopes, intercepts).
            if key not in [2, 3, 4, 5, '2', '3', '4', '5']:
                continue
                
            prefix = test_id_map[int(key)]
            x_data = data_dict['X']
            y_data = data_dict['Y']
            
            data_to_export[f"{prefix}_X"] = x_data
            data_to_export[f"{prefix}_Y"] = y_data
            
            if len(x_data) > max_len:
                max_len = len(x_data)
                
        if not data_to_export:
            print("No data to export.")
            return

        # Pad with NaNs to make lengths equal
        for col, data in data_to_export.items():
            if len(data) < max_len:
                data_to_export[col] = data + [np.nan] * (max_len - len(data))
                
        df = pd.DataFrame(data_to_export)
        
        os.makedirs(DATALOG_PATH, exist_ok=True)
        timestamp = time.strftime('%Y%m%d_%H%M%S')
        filename = f"{PART_NUMBER}_{self.serial_number}_{timestamp}.csv"
        filepath = os.path.join(DATALOG_PATH, filename)
        
        df.to_csv(filepath, index=False)
        print(f"Data exported to {filepath}")
       
if __name__ == "__main__":
           
    tpi = TPI()
    
    # Test Sequence
    tpi.startup()
    tpi.preUUT()
    
    
    tpi.testExecution(test_id=0)
    tpi.testExecution(test_id=1)            
    # Wait for the user to close the 3-way plot before proceeding
    
    tpi._is_switching_windows = True
    plt.show()
    tpi._is_switching_windows = False

    # Open a clean window for the 4-way Lap test
    tpi.xyplotter = XYPlotter(update_interval = 50)
    tpi.xyplotter.btn_run.on_clicked(tpi.restart_test)
    tpi.xyplotter.fig.canvas.mpl_connect('close_event', tpi.on_close)
    tpi.xyplotter.part_text.set_text(tpi.text_box)

    tpi.testExecution(test_id=2) # Add pauseing time plt.pause(1)    
    tpi.testExecution(test_id=3)
    tpi.testExecution(test_id=4)
    tpi.testExecution(test_id=5)
    tpi.testExecution(test_id=6)
    plt.show()
    
    tpi.postUUT()
    
