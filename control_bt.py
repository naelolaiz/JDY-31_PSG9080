#!/usr/bin/env python3
import sys
import asyncio
import binascii
from bleak import BleakClient
from PyQt5.QtWidgets import (QApplication, QMainWindow, QTabWidget, QWidget, 
                            QVBoxLayout, QHBoxLayout, QLabel, QComboBox, 
                            QLineEdit, QPushButton, QGroupBox, QSlider, QSpinBox,
                            QDoubleSpinBox, QCheckBox, QGridLayout, QFormLayout,
                            QProgressBar, QRadioButton, QButtonGroup)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, pyqtSlot

# Device Address - Replace with your device's MAC address
DEVICE_ADDRESS = "5C:53:10:DA:D2:DD"
# Characteristic UUIDs
COMMAND_CHARACTERISTIC_UUID = "0000fff2-0000-1000-8000-00805f9b34fb"  # For writing commands
RESPONSE_CHARACTERISTIC_UUID = "0000fff1-0000-1000-8000-00805f9b34fb"  # For receiving responses

# Define waveform options
WAVEFORMS = {
    "Sine": 0,
    "Square": 1,
    "Pulse": 2,
    "Triangle": 3,
    "Slope": 4,
    "CMOS": 5,
    "DC level": 6,
    "Partial sine wave": 7,
    "Half wave": 8,
    "Full wave": 9,
    "Positive ladder wave": 10,
    "Negative ladder wave": 11,
    "Positive trapezoidal wave": 12,
    "Negative trapezoidal wave": 13,
    "Noise wave": 14,
    "Index rise": 15,
    "Index fall": 16,
    "Logarithmic rise": 17,
    "Logarithmic fall": 18,
    "Sinker Pulse": 19,
    "Multi-audio": 20,
    "Lorenz": 21,
}

# Define frequency unit options
FREQ_UNITS = {
    "Hz": 0,
    "kHz": 1,
    "MHz": 2,
    "mHz": 3,
    "μHz": 4,
}

# Define modulation types
MODULATION_TYPES = {
    "AM": 0,
    "FM": 1,
    "PM": 2,
    "ASK": 3,
    "FSK": 4, 
    "PSK": 5,
    "PULSE": 6,
    "BURST": 7
}

# Define modulation wave types
MODULATION_WAVES = {
    "Sine": 0,
    "Square": 1,
    "Triangle": 2,
    "Rising sawtooth": 3,
    "Falling sawtooth": 4,
    "Arbitrary wave 101": 5,
    "Arbitrary wave 102": 6,
    "Arbitrary wave 103": 7,
    "Arbitrary wave 104": 8,
    "Arbitrary wave 105": 9
}

# Define modulation source options
MODULATION_SOURCES = {
    "Internal": 0,
    "External": 1
}

# Define trigger sources
TRIGGER_SOURCES = {
    "Key": 0,
    "Internal": 1,
    "External AC": 2,
    "External DC": 3
}

# Define burst wave idle modes
BURST_IDLE_MODES = {
    "Zero": 0,
    "Positive maximum": 1,
    "Negative maximum": 2
}

# Define polarity options
POLARITY_OPTIONS = {
    "Positive polarity": 0,
    "Negative polarity": 1
}

# Define pulse wave inversion
PULSE_INVERSION = {
    "Normal": 0,
    "Inversion": 1
}

# Simplified command and read command patterns - most commands just differ by channel number
PARAM_COMMANDS = {
    "output": "w10",      # Special case for output - manages both channels
    "waveform": "w1{}",   # Formats to w11, w12 based on channel
    "frequency": "w1{}",  # Formats to w13, w14 based on channel+2
    "amplitude": "w1{}",  # Formats to w15, w16 based on channel+4
    "offset": "w1{}",     # Formats to w17, w18 based on channel+6
    "duty": "w{}",        # Formats to w19, w20 based on channel+18
    "phase": "w2{}",      # Formats to w21, w22 based on channel
}

# Table to map parameter to the offset added to the channel number
PARAM_OFFSETS = {
    "waveform": 0,    # w11, w12
    "frequency": 2,   # w13, w14
    "amplitude": 4,   # w15, w16
    "offset": 6,      # w17, w18
    "duty": 18,       # w19, w20 (special case)
    "phase": 0,       # w21, w22 (w2 series)
}

class BLEWorker(QThread):
    connected = pyqtSignal(bool)
    message_received = pyqtSignal(str)
    notification_received = pyqtSignal(str)
    status_updated = pyqtSignal(dict)
    refresh_started = pyqtSignal()
    refresh_completed = pyqtSignal()
    refresh_progress = pyqtSignal(int, int)  # Current, total
    measurement_updated = pyqtSignal(dict)   # New signal for measurement updates
    
    def __init__(self, address):
        super().__init__()
        self.address = address
        self.client = None
        self.loop = None
        self.running = False
        self.command_queue = asyncio.Queue()
        self.status = {}
        self.measurement_data = {}  # Store measurement readings
        self.refreshing = False
        
    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.running = True
        self.loop.run_until_complete(self.run_ble_client())
        
    def notification_handler(self, sender, data):
        """Handle incoming notifications from the device"""
        try:
            message = data.decode('utf-8').strip()
            self.notification_received.emit(message)
            
            # Parse status response
            if message.startswith(':r'):
                self.parse_status_response(message)
                
        except Exception as e:
            self.message_received.emit(f"Error processing notification: {str(e)}")
    
    def parse_status_response(self, response):
        """Parse a status response and update the status dictionary"""
        try:
            # Basic parsing - can be enhanced for specific commands
            if '=' in response:
                cmd, value = response.split('=', 1)
                cmd = cmd.strip()
                cmd_type = cmd[2:]  # Remove ":r" prefix
                
                # Parse different response types
                if cmd_type == '10':  # Output status
                    parts = value.split(',')
                    if len(parts) >= 2:
                        self.status['ch1_output'] = parts[0].strip() == '1'
                        self.status['ch2_output'] = parts[1].strip() == '1'
                
                # Handle the basic parameters (waveform, frequency, etc.)
                elif (cmd_type.startswith('1') or cmd_type.startswith('2')) and int(cmd_type) <= 22:
                    # Extract channel number based on command pattern
                    if cmd_type.startswith('1'):
                        # Handle r1x series (11-20)
                        cmd_num = int(cmd_type[1])
                        
                        if cmd_num <= 2:
                            # Commands 11, 12 (waveform)
                            channel = cmd_num
                            self.status[f'ch{channel}_waveform'] = int(value.strip('.\r\n'))
                        elif cmd_num <= 4:
                            # Commands 13, 14 (frequency)
                            channel = cmd_num - 2
                            parts = value.split(',')
                            if len(parts) >= 2:
                                freq_val = int(parts[0].strip()) / 1000.0  # Convert to decimal
                                freq_unit = int(parts[1].strip('.\r\n'))
                                self.status[f'ch{channel}_frequency'] = freq_val
                                self.status[f'ch{channel}_freq_unit'] = freq_unit
                        elif cmd_num <= 6:
                            # Commands 15, 16 (amplitude)
                            channel = cmd_num - 4
                            self.status[f'ch{channel}_amplitude'] = int(value.strip('.\r\n')) / 1000.0
                        elif cmd_num <= 8:
                            # Commands 17, 18 (offset)
                            channel = cmd_num - 6
                            offset_val = int(value.strip('.\r\n'))
                            if offset_val == 1000:
                                self.status[f'ch{channel}_offset'] = 0
                            else:
                                self.status[f'ch{channel}_offset'] = (offset_val - 1000) / 100.0
                        elif cmd_num == 9:
                            # Command 19 (duty for channel 1)
                            channel = 1
                            self.status[f'ch{channel}_duty'] = int(value.strip('.\r\n')) / 100.0
                        elif cmd_num == 0:
                            # Command 20 (duty for channel 2)
                            channel = 2
                            self.status[f'ch{channel}_duty'] = int(value.strip('.\r\n')) / 100.0
                            
                    elif cmd_type.startswith('2'):
                        # Handle r2x series (21-22)
                        num = int(cmd_type[1])
                        if num <= 2:
                            # Commands 21, 22 (phase)
                            channel = num
                            self.status[f'ch{channel}_phase'] = int(value.strip('.\r\n')) / 100.0
                
                # Handle modulation settings (r40-r56)
                elif cmd_type.startswith('4') or (cmd_type.startswith('5') and int(cmd_type) <= 56):
                    cmd_num = int(cmd_type)
                    
                    if cmd_num == 40:  # Modulation type
                        parts = value.split(',')
                        if len(parts) >= 2:
                            self.status['ch1_mod_type'] = int(parts[0].strip())
                            self.status['ch2_mod_type'] = int(parts[1].strip('.\r\n'))
                    
                    elif cmd_num == 41:  # Modulation built-in wave type
                        parts = value.split(',')
                        if len(parts) >= 2:
                            self.status['ch1_mod_wave'] = int(parts[0].strip())
                            self.status['ch2_mod_wave'] = int(parts[1].strip('.\r\n'))
                    
                    elif cmd_num == 42:  # Modulation source
                        parts = value.split(',')
                        if len(parts) >= 2:
                            self.status['ch1_mod_source'] = int(parts[0].strip())
                            self.status['ch2_mod_source'] = int(parts[1].strip('.\r\n'))
                    
                    elif cmd_num == 43:  # CH1 built-in wave frequency
                        self.status['ch1_mod_freq'] = int(value.strip('.\r\n')) / 1000.0
                    
                    elif cmd_num == 44:  # CH2 built-in wave frequency
                        self.status['ch2_mod_freq'] = int(value.strip('.\r\n')) / 1000.0
                    
                    elif cmd_num == 45:  # CH1 AM modulation depth
                        self.status['ch1_am_depth'] = int(value.strip('.\r\n')) / 10.0
                    
                    elif cmd_num == 46:  # CH2 AM modulation depth
                        self.status['ch2_am_depth'] = int(value.strip('.\r\n')) / 10.0
                    
                    elif cmd_num == 47:  # CH1 FM frequency deviation
                        self.status['ch1_fm_deviation'] = int(value.strip('.\r\n')) / 10.0
                    
                    elif cmd_num == 48:  # CH2 FM frequency deviation
                        self.status['ch2_fm_deviation'] = int(value.strip('.\r\n')) / 10.0
                    
                    elif cmd_num == 49:  # CH1 FSK hopping frequency
                        self.status['ch1_fsk_hopping'] = int(value.strip('.\r\n')) / 10.0
                    
                    elif cmd_num == 50:  # CH2 FSK hopping frequency
                        self.status['ch2_fsk_hopping'] = int(value.strip('.\r\n')) / 10.0
                    
                    elif cmd_num == 51:  # CH1 PM phase deviation
                        self.status['ch1_pm_phase'] = int(value.strip('.\r\n')) / 10.0
                    
                    elif cmd_num == 52:  # CH2 PM phase deviation
                        self.status['ch2_pm_phase'] = int(value.strip('.\r\n')) / 10.0
                    
                    elif cmd_num == 53:  # CH1 pulse width
                        self.status['ch1_pulse_width'] = int(value.strip('.\r\n')) / 1000.0
                    
                    elif cmd_num == 54:  # CH2 pulse width
                        self.status['ch2_pulse_width'] = int(value.strip('.\r\n')) / 1000.0
                    
                    elif cmd_num == 55:  # CH1 pulse period
                        self.status['ch1_pulse_period'] = int(value.strip('.\r\n')) / 100.0
                    
                    elif cmd_num == 56:  # CH2 pulse period
                        self.status['ch2_pulse_period'] = int(value.strip('.\r\n')) / 100.0
                
                # Handle burst settings (r57-r61)
                elif cmd_type.startswith('5') and int(cmd_type) >= 57 and int(cmd_type) <= 61:
                    cmd_num = int(cmd_type)
                    
                    if cmd_num == 57:  # Pulse wave inversion
                        parts = value.split(',')
                        if len(parts) >= 2:
                            self.status['ch1_pulse_inversion'] = int(parts[0].strip())
                            self.status['ch2_pulse_inversion'] = int(parts[1].strip('.\r\n'))
                    
                    elif cmd_num == 58:  # Burst wave idle
                        parts = value.split(',')
                        if len(parts) >= 2:
                            self.status['ch1_burst_idle'] = int(parts[0].strip())
                            self.status['ch2_burst_idle'] = int(parts[1].strip('.\r\n'))
                    
                    elif cmd_num == 59:  # Polarity
                        parts = value.split(',')
                        if len(parts) >= 2:
                            self.status['ch1_polarity'] = int(parts[0].strip())
                            self.status['ch2_polarity'] = int(parts[1].strip('.\r\n'))
                    
                    elif cmd_num == 60:  # Trigger source
                        parts = value.split(',')
                        if len(parts) >= 2:
                            self.status['ch1_trigger_source'] = int(parts[0].strip())
                            self.status['ch2_trigger_source'] = int(parts[1].strip('.\r\n'))
                    
                    elif cmd_num == 61:  # Burst pulse number
                        parts = value.split(',')
                        if len(parts) >= 2:
                            self.status['ch1_burst_count'] = int(parts[0].strip())
                            self.status['ch2_burst_count'] = int(parts[1].strip('.\r\n'))
                
                # Handle measurement responses (r80-r86)
                elif cmd_type.startswith('8'):
                    cmd_num = int(cmd_type)
                    
                    if cmd_num == 80:  # Count value
                        self.measurement_data['count'] = int(value.strip('.\r\n'))
                    
                    elif cmd_num == 81:  # High frequency measurement
                        self.measurement_data['high_freq'] = int(value.strip('.\r\n')) / 1000.0
                    
                    elif cmd_num == 82:  # Low frequency measurement
                        self.measurement_data['low_freq'] = int(value.strip('.\r\n')) / 1000.0
                    
                    elif cmd_num == 83:  # Positive pulse width
                        self.measurement_data['pos_pulse_width'] = int(value.strip('.\r\n')) / 1000.0
                    
                    elif cmd_num == 84:  # Negative pulse width
                        self.measurement_data['neg_pulse_width'] = int(value.strip('.\r\n')) / 1000.0
                    
                    elif cmd_num == 85:  # Period
                        self.measurement_data['period'] = int(value.strip('.\r\n')) / 100.0
                    
                    elif cmd_num == 86:  # Duty cycle
                        self.measurement_data['duty_cycle'] = int(value.strip('.\r\n')) / 100.0
                    
                    # Emit the measurement data update
                    self.measurement_updated.emit(self.measurement_data)
                
                # Emit signal with updated status
                self.status_updated.emit(self.status)
                
        except Exception as e:
            self.message_received.emit(f"Error parsing status response: {str(e)}")
            
    async def run_ble_client(self):
        try:
            self.client = BleakClient(self.address)
            await self.client.connect()
            self.connected.emit(True)
            self.message_received.emit(f"Connected to {self.address}")
            
            # Enable notifications for response characteristic
            await self.client.start_notify(RESPONSE_CHARACTERISTIC_UUID, self.notification_handler)
            self.message_received.emit("Notifications enabled")
            
            # Query current device status
            await self.query_device_status()
            
            # Process commands from the queue
            while self.running:
                try:
                    command = await asyncio.wait_for(self.command_queue.get(), timeout=0.1)
                    await self.send_command(command)
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    self.message_received.emit(f"Error processing command: {str(e)}")
                    
        except Exception as e:
            self.message_received.emit(f"Connection error: {str(e)}")
            self.connected.emit(False)
        finally:
            if self.client and self.client.is_connected:
                try:
                    await self.client.stop_notify(RESPONSE_CHARACTERISTIC_UUID)
                except:
                    pass
                await self.client.disconnect()
            self.connected.emit(False)
            self.message_received.emit("Disconnected")
    
    async def query_device_status(self):
        """Query the device for its current settings"""
        self.message_received.emit("Querying device status...")
        self.refreshing = True
        self.refresh_started.emit()
        
        # Generate read commands based on parameter patterns
        read_commands = []
        
        # Add output status (a single command for both channels)
        read_commands.append(":r10=0.")
        
        # Generate other read commands for each parameter and channel
        params = ["waveform", "frequency", "amplitude", "offset", "duty", "phase"]
        channels = [1, 2]
        
        for param in params:
            for channel in channels:
                if param == "waveform" or param == "frequency" or param == "amplitude" or param == "offset":
                    # These use the r1x pattern
                    cmd_num = channel + PARAM_OFFSETS[param]
                    read_commands.append(f":r1{cmd_num}=0.")
                elif param == "duty":
                    # Special case for duty cycle (r19, r20)
                    cmd_num = channel + 18  # 19 for ch1, 20 for ch2
                    read_commands.append(f":r{cmd_num}=0.")
                elif param == "phase":
                    # These use the r2x pattern
                    read_commands.append(f":r2{channel}=0.")
        
        # Add modulation read commands
        for cmd in range(40, 57):
            read_commands.append(f":r{cmd}=0.")
            
        # Add burst settings read commands
        for cmd in range(57, 62):
            read_commands.append(f":r{cmd}=0.")

        # Add measurement read commands
        for cmd in range(80, 87):
            read_commands.append(f":r{cmd}=0.")
            
        # Add trigger and counter read commands
        read_commands.extend([":r62=0.", ":r63=0."])
        
        total_commands = len(read_commands)
        for i, cmd in enumerate(read_commands):
            await self.send_command(cmd)
            # Update progress
            self.refresh_progress.emit(i + 1, total_commands)
            # Give the device time to respond
            await asyncio.sleep(0.2)
            
        self.refreshing = False
        self.refresh_completed.emit()
            
    async def send_command(self, command):
        if not self.client or not self.client.is_connected:
            self.message_received.emit("Not connected. Cannot send command.")
            return
            
        try:
            # Convert command string to bytes, adding CR+LF
            if not command.endswith('\r\n'):
                command += '\r\n'
            
            command_bytes = command.encode('utf-8')
            self.message_received.emit(f"Sending: {command}")
            
            await self.client.write_gatt_char(COMMAND_CHARACTERISTIC_UUID, command_bytes)
            self.message_received.emit(f"Command sent successfully")
            
            # Wait briefly for notification response
            await asyncio.sleep(0.1)
            
        except Exception as e:
            self.message_received.emit(f"Error sending command: {str(e)}")
    
    def queue_command(self, command):
        if self.loop:
            asyncio.run_coroutine_threadsafe(self.command_queue.put(command), self.loop)
    
    def stop(self):
        self.running = False
        self.wait()
    
    def query_specific_setting(self, read_command):
        """Queue a specific read command"""
        if self.loop:
            asyncio.run_coroutine_threadsafe(self.command_queue.put(read_command), self.loop)


class SignalGeneratorUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.ble_worker = BLEWorker(DEVICE_ADDRESS)
        self.ble_worker.connected.connect(self.update_connection_status)
        self.ble_worker.message_received.connect(self.update_message_log)
        self.ble_worker.notification_received.connect(self.update_notification_log)
        self.ble_worker.status_updated.connect(self.update_ui_from_status)
        self.ble_worker.refresh_started.connect(self.on_refresh_started)
        self.ble_worker.refresh_completed.connect(self.on_refresh_completed)
        self.ble_worker.refresh_progress.connect(self.update_refresh_progress)
        self.ble_worker.measurement_updated.connect(self.update_measurement_display)
        self.ble_worker.start()
        
        self.channel_controls = {}  # Store controls by channel for easy access
        self.modulation_controls = {}  # Store modulation controls
        self.measurement_controls = {}  # Store measurement controls
        self.sweep_controls = {}  # Store sweep controls
        self.all_ui_controls = []   # List of all controls that can be enabled/disabled
        
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle('Signal Generator Control')
        self.setGeometry(100, 100, 1000, 700)
        
        # Main layout
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        
        # Connection status
        connection_layout = QHBoxLayout()
        self.connection_status = QLabel("Disconnected")
        connection_layout.addWidget(QLabel("Status:"))
        connection_layout.addWidget(self.connection_status)
        connection_layout.addStretch(1)
        
        # Manual command input
        manual_cmd_layout = QHBoxLayout()
        self.cmd_input = QLineEdit()
        self.cmd_input.setPlaceholderText("Enter command (e.g., :w11=0.)")
        self.all_ui_controls.append(self.cmd_input)
        
        send_btn = QPushButton("Send")
        send_btn.clicked.connect(self.send_manual_command)
        self.all_ui_controls.append(send_btn)
        
        manual_cmd_layout.addWidget(self.cmd_input)
        manual_cmd_layout.addWidget(send_btn)
        
        # Message logs
        logs_group = QGroupBox("Communication Log")
        logs_layout = QVBoxLayout(logs_group)
        
        # Command log
        cmd_log_layout = QHBoxLayout()
        cmd_log_layout.addWidget(QLabel("Commands:"))
        self.message_log = QLineEdit()
        self.message_log.setReadOnly(True)
        cmd_log_layout.addWidget(self.message_log)
        
        # Notification log
        notify_log_layout = QHBoxLayout()
        notify_log_layout.addWidget(QLabel("Response:"))
        self.notification_log = QLineEdit()
        self.notification_log.setReadOnly(True)
        notify_log_layout.addWidget(self.notification_log)
        
        logs_layout.addLayout(cmd_log_layout)
        logs_layout.addLayout(notify_log_layout)
        
        # Progress bar for refresh operation
        progress_layout = QHBoxLayout()
        progress_layout.addWidget(QLabel("Refresh Progress:"))
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        progress_layout.addWidget(self.progress_bar)
        
        logs_layout.addLayout(progress_layout)
        
        # Create tabs for different channels
        self.tab_widget = QTabWidget()
        self.all_ui_controls.append(self.tab_widget)
        
        # Initialize each channel
        self.channel_controls[1] = {}  # Controls for channel 1
        self.channel_controls[2] = {}  # Controls for channel 2
        
        # Create each channel tab
        for channel in [1, 2]:
            tab = self.create_channel_tab(channel)
            self.tab_widget.addTab(tab, f"Channel {channel}")
        
        # Create modulation tab
        modulation_tab = self.create_modulation_tab()
        self.tab_widget.addTab(modulation_tab, "Modulation")
        
        # Create measurement/counter tab
        measurement_tab = self.create_measurement_tab()
        self.tab_widget.addTab(measurement_tab, "Measurement")
        
        # Create sweep tab
        sweep_tab = self.create_sweep_tab()
        self.tab_widget.addTab(sweep_tab, "Sweep")
        
        # Refresh button
        refresh_btn = QPushButton("Refresh Device Status")
        refresh_btn.clicked.connect(self.refresh_device_status)
        self.all_ui_controls.append(refresh_btn)
        
        # Add widgets to main layout
        main_layout.addLayout(connection_layout)
        main_layout.addLayout(manual_cmd_layout)
        main_layout.addWidget(logs_group)
        main_layout.addWidget(refresh_btn)
        main_layout.addWidget(self.tab_widget)
        
        self.setCentralWidget(main_widget)
        
    def create_channel_tab(self, channel):
        """Create a tab for controlling a specific channel"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Waveform control
        waveform_group = QGroupBox("Waveform")
        waveform_layout = QFormLayout(waveform_group)
        
        # On/Off control
        enable = QCheckBox("Enable Output")
        enable.stateChanged.connect(lambda state, ch=channel: self.update_parameter(ch, "output", state))
        waveform_layout.addRow("Output:", enable)
        self.channel_controls[channel]["enable"] = enable
        self.all_ui_controls.append(enable)
        
        # Waveform type
        waveform = QComboBox()
        for wave_name in WAVEFORMS:
            waveform.addItem(wave_name)
        waveform.currentIndexChanged.connect(lambda _, ch=channel: self.update_parameter(ch, "waveform"))
        waveform_layout.addRow("Type:", waveform)
        self.channel_controls[channel]["waveform"] = waveform
        self.all_ui_controls.append(waveform)
        
        # Frequency
        freq_layout = QHBoxLayout()
        frequency = QDoubleSpinBox()
        frequency.setRange(0, 1000000)
        frequency.setDecimals(3)
        frequency.setValue(1000)
        frequency.valueChanged.connect(lambda _, ch=channel: self.update_parameter(ch, "frequency"))
        self.all_ui_controls.append(frequency)
        
        freq_unit = QComboBox()
        for unit in FREQ_UNITS:
            freq_unit.addItem(unit)
        freq_unit.currentIndexChanged.connect(lambda _, ch=channel: self.update_parameter(ch, "frequency"))
        self.all_ui_controls.append(freq_unit)
        
        freq_layout.addWidget(frequency)
        freq_layout.addWidget(freq_unit)
        waveform_layout.addRow("Frequency:", freq_layout)
        self.channel_controls[channel]["frequency"] = frequency
        self.channel_controls[channel]["freq_unit"] = freq_unit
        
        # Amplitude
        amplitude = QDoubleSpinBox()
        amplitude.setRange(0, 20)
        amplitude.setDecimals(3)
        amplitude.setValue(5)
        amplitude.valueChanged.connect(lambda _, ch=channel: self.update_parameter(ch, "amplitude"))
        waveform_layout.addRow("Amplitude (Vpp):", amplitude)
        self.channel_controls[channel]["amplitude"] = amplitude
        self.all_ui_controls.append(amplitude)
        
        # Offset
        offset = QDoubleSpinBox()
        offset.setRange(-10, 10)
        offset.setDecimals(2)
        offset.setValue(0)
        offset.valueChanged.connect(lambda _, ch=channel: self.update_parameter(ch, "offset"))
        waveform_layout.addRow("Offset (V):", offset)
        self.channel_controls[channel]["offset"] = offset
        self.all_ui_controls.append(offset)
        
        # Duty Cycle (for square, pulse)
        duty = QDoubleSpinBox()
        duty.setRange(0, 100)
        duty.setDecimals(2)
        duty.setValue(50)
        duty.valueChanged.connect(lambda _, ch=channel: self.update_parameter(ch, "duty"))
        waveform_layout.addRow("Duty Cycle (%):", duty)
        self.channel_controls[channel]["duty"] = duty
        self.all_ui_controls.append(duty)
        
        # Phase
        phase = QDoubleSpinBox()
        phase.setRange(0, 360)
        phase.setDecimals(2)
        phase.setValue(0)
        phase.valueChanged.connect(lambda _, ch=channel: self.update_parameter(ch, "phase"))
        waveform_layout.addRow("Phase (°):", phase)
        self.channel_controls[channel]["phase"] = phase
        self.all_ui_controls.append(phase)
        
        # Apply all button
        apply_all_btn = QPushButton("Apply All Settings")
        apply_all_btn.clicked.connect(lambda _, ch=channel: self.apply_all_settings(ch))
        self.all_ui_controls.append(apply_all_btn)
        
        layout.addWidget(waveform_group)
        layout.addWidget(apply_all_btn)
        layout.addStretch(1)
        
        return tab

    def create_modulation_tab(self):
        """Create the modulation tab with controls for both channels"""
        tab = QWidget()
        main_layout = QVBoxLayout(tab)
        
        # Channel tabs for modulation
        channel_tabs = QTabWidget()
        
        for channel in [1, 2]:
            ch_tab = QWidget()
            ch_layout = QVBoxLayout(ch_tab)
            
            # Modulation type group
            mod_type_group = QGroupBox("Modulation Type")
            mod_type_layout = QVBoxLayout(mod_type_group)
            
            # Type selection
            mod_type = QComboBox()
            for mod_name in MODULATION_TYPES:
                mod_type.addItem(mod_name)
            mod_type.currentIndexChanged.connect(lambda idx, ch=channel: self.update_modulation_type(ch, idx))
            mod_type_layout.addWidget(mod_type)
            
            if channel not in self.modulation_controls:
                self.modulation_controls[channel] = {}
            self.modulation_controls[channel]["type"] = mod_type
            self.all_ui_controls.append(mod_type)
            
            ch_layout.addWidget(mod_type_group)
            
            # Modulation source group
            mod_source_group = QGroupBox("Modulation Source")
            mod_source_layout = QVBoxLayout(mod_source_group)
            
            # Source selection
            mod_source = QComboBox()
            for source in MODULATION_SOURCES:
                mod_source.addItem(source)
            mod_source.currentIndexChanged.connect(lambda idx, ch=channel: self.update_modulation_source(ch, idx))
            mod_source_layout.addWidget(mod_source)
            
            self.modulation_controls[channel]["source"] = mod_source
            self.all_ui_controls.append(mod_source)
            
            ch_layout.addWidget(mod_source_group)
            
            # Modulation wave type group (for internal source)
            mod_wave_group = QGroupBox("Modulation Wave")
            mod_wave_layout = QVBoxLayout(mod_wave_group)
            
            # Wave type selection
            mod_wave = QComboBox()
            for wave in MODULATION_WAVES:
                mod_wave.addItem(wave)
            mod_wave.currentIndexChanged.connect(lambda idx, ch=channel: self.update_modulation_wave(ch, idx))
            mod_wave_layout.addWidget(mod_wave)
            
            self.modulation_controls[channel]["wave"] = mod_wave
            self.all_ui_controls.append(mod_wave)
            
            # Modulation frequency (for internal source)
            mod_freq_layout = QHBoxLayout()
            mod_freq_layout.addWidget(QLabel("Frequency:"))
            
            mod_freq = QDoubleSpinBox()
            mod_freq.setRange(0, 100000)
            mod_freq.setDecimals(3)
            mod_freq.setValue(500)
            mod_freq.valueChanged.connect(lambda val, ch=channel: self.update_modulation_frequency(ch, val))
            mod_freq_layout.addWidget(mod_freq)
            mod_freq_layout.addWidget(QLabel("Hz"))
            
            self.modulation_controls[channel]["frequency"] = mod_freq
            self.all_ui_controls.append(mod_freq)
            
            mod_wave_layout.addLayout(mod_freq_layout)
            
            ch_layout.addWidget(mod_wave_group)
            
            # Parameter groups - AM, FM, PM, etc.
            params_group = QGroupBox("Modulation Parameters")
            params_layout = QVBoxLayout(params_group)
            
            # AM Depth
            am_depth_layout = QHBoxLayout()
            am_depth_layout.addWidget(QLabel("AM Depth:"))
            
            am_depth = QDoubleSpinBox()
            am_depth.setRange(0, 100)
            am_depth.setDecimals(1)
            am_depth.setValue(80)
            am_depth.valueChanged.connect(lambda val, ch=channel: self.update_am_depth(ch, val))
            am_depth_layout.addWidget(am_depth)
            am_depth_layout.addWidget(QLabel("%"))
            
            self.modulation_controls[channel]["am_depth"] = am_depth
            self.all_ui_controls.append(am_depth)
            
            params_layout.addLayout(am_depth_layout)
            
            # FM Deviation
            fm_dev_layout = QHBoxLayout()
            fm_dev_layout.addWidget(QLabel("FM Deviation:"))
            
            fm_dev = QDoubleSpinBox()
            fm_dev.setRange(0, 100000)
            fm_dev.setDecimals(1)
            fm_dev.setValue(2000)
            fm_dev.valueChanged.connect(lambda val, ch=channel: self.update_fm_deviation(ch, val))
            fm_dev_layout.addWidget(fm_dev)
            fm_dev_layout.addWidget(QLabel("Hz"))
            
            self.modulation_controls[channel]["fm_deviation"] = fm_dev
            self.all_ui_controls.append(fm_dev)
            
            params_layout.addLayout(fm_dev_layout)
            
            # PM Phase
            pm_phase_layout = QHBoxLayout()
            pm_phase_layout.addWidget(QLabel("PM Phase:"))
            
            pm_phase = QDoubleSpinBox()
            pm_phase.setRange(0, 359.9)
            pm_phase.setDecimals(1)
            pm_phase.setValue(180)
            pm_phase.valueChanged.connect(lambda val, ch=channel: self.update_pm_phase(ch, val))
            pm_phase_layout.addWidget(pm_phase)
            pm_phase_layout.addWidget(QLabel("°"))
            
            self.modulation_controls[channel]["pm_phase"] = pm_phase
            self.all_ui_controls.append(pm_phase)
            
            params_layout.addLayout(pm_phase_layout)
            
            # FSK Hopping Frequency
            fsk_hop_layout = QHBoxLayout()
            fsk_hop_layout.addWidget(QLabel("FSK Hopping:"))
            
            fsk_hop = QDoubleSpinBox()
            fsk_hop.setRange(0, 100000)
            fsk_hop.setDecimals(1)
            fsk_hop.setValue(2000)
            fsk_hop.valueChanged.connect(lambda val, ch=channel: self.update_fsk_hopping(ch, val))
            fsk_hop_layout.addWidget(fsk_hop)
            fsk_hop_layout.addWidget(QLabel("Hz"))
            
            self.modulation_controls[channel]["fsk_hopping"] = fsk_hop
            self.all_ui_controls.append(fsk_hop)
            
            params_layout.addLayout(fsk_hop_layout)
            
            # Pulse Width
            pulse_width_layout = QHBoxLayout()
            pulse_width_layout.addWidget(QLabel("Pulse Width:"))
            
            pulse_width = QDoubleSpinBox()
            pulse_width.setRange(0, 400)
            pulse_width.setDecimals(3)
            pulse_width.setValue(0.1)
            pulse_width.valueChanged.connect(lambda val, ch=channel: self.update_pulse_width(ch, val))
            pulse_width_layout.addWidget(pulse_width)
            pulse_width_layout.addWidget(QLabel("μs"))
            
            self.modulation_controls[channel]["pulse_width"] = pulse_width
            self.all_ui_controls.append(pulse_width)
            
            params_layout.addLayout(pulse_width_layout)
            
            # Pulse Period
            pulse_period_layout = QHBoxLayout()
            pulse_period_layout.addWidget(QLabel("Pulse Period:"))
            
            pulse_period = QDoubleSpinBox()
            pulse_period.setRange(0, 4000)
            pulse_period.setDecimals(2)
            pulse_period.setValue(10)
            pulse_period.valueChanged.connect(lambda val, ch=channel: self.update_pulse_period(ch, val))
            pulse_period_layout.addWidget(pulse_period)
            pulse_period_layout.addWidget(QLabel("μs"))
            
            self.modulation_controls[channel]["pulse_period"] = pulse_period
            self.all_ui_controls.append(pulse_period)
            
            params_layout.addLayout(pulse_period_layout)
            
            # Burst Count
            burst_count_layout = QHBoxLayout()
            burst_count_layout.addWidget(QLabel("Burst Count:"))
            
            burst_count = QSpinBox()
            burst_count.setRange(1, 1000000)
            burst_count.setValue(1000)
            burst_count.valueChanged.connect(lambda val, ch=channel: self.update_burst_count(ch, val))
            burst_count_layout.addWidget(burst_count)
            
            self.modulation_controls[channel]["burst_count"] = burst_count
            self.all_ui_controls.append(burst_count)
            
            params_layout.addLayout(burst_count_layout)
            
            ch_layout.addWidget(params_group)
            
            # Burst/Pulse Settings
            burst_group = QGroupBox("Burst/Pulse Settings")
            burst_layout = QVBoxLayout(burst_group)
            
            # Pulse Wave Inversion
            inversion_layout = QHBoxLayout()
            inversion_layout.addWidget(QLabel("Pulse Inversion:"))
            
            inversion = QComboBox()
            for inv in PULSE_INVERSION:
                inversion.addItem(inv)
            inversion.currentIndexChanged.connect(lambda idx, ch=channel: self.update_pulse_inversion(ch, idx))
            inversion_layout.addWidget(inversion)
            
            self.modulation_controls[channel]["pulse_inversion"] = inversion
            self.all_ui_controls.append(inversion)
            
            burst_layout.addLayout(inversion_layout)
            
            # Burst Wave Idle Mode
            idle_layout = QHBoxLayout()
            idle_layout.addWidget(QLabel("Burst Idle Mode:"))
            
            idle_mode = QComboBox()
            for mode in BURST_IDLE_MODES:
                idle_mode.addItem(mode)
            idle_mode.currentIndexChanged.connect(lambda idx, ch=channel: self.update_burst_idle(ch, idx))
            idle_layout.addWidget(idle_mode)
            
            self.modulation_controls[channel]["burst_idle"] = idle_mode
            self.all_ui_controls.append(idle_mode)
            
            burst_layout.addLayout(idle_layout)
            
            # Signal Polarity
            polarity_layout = QHBoxLayout()
            polarity_layout.addWidget(QLabel("Signal Polarity:"))
            
            polarity = QComboBox()
            for pol in POLARITY_OPTIONS:
                polarity.addItem(pol)
            polarity.currentIndexChanged.connect(lambda idx, ch=channel: self.update_polarity(ch, idx))
            polarity_layout.addWidget(polarity)
            
            self.modulation_controls[channel]["polarity"] = polarity
            self.all_ui_controls.append(polarity)
            
            burst_layout.addLayout(polarity_layout)
            
            # Trigger Source
            trigger_layout = QHBoxLayout()
            trigger_layout.addWidget(QLabel("Trigger Source:"))
            
            trigger = QComboBox()
            for src in TRIGGER_SOURCES:
                trigger.addItem(src)
            trigger.currentIndexChanged.connect(lambda idx, ch=channel: self.update_trigger_source(ch, idx))
            trigger_layout.addWidget(trigger)
            
            self.modulation_controls[channel]["trigger_source"] = trigger
            self.all_ui_controls.append(trigger)
            
            burst_layout.addLayout(trigger_layout)
            
            ch_layout.addWidget(burst_group)
            
            # Apply Modulation Settings button
            apply_mod_btn = QPushButton("Apply Modulation Settings")
            apply_mod_btn.clicked.connect(lambda _, ch=channel: self.apply_modulation_settings(ch))
            self.all_ui_controls.append(apply_mod_btn)
            
            ch_layout.addWidget(apply_mod_btn)
            ch_layout.addStretch(1)
            
            channel_tabs.addTab(ch_tab, f"Channel {channel}")
        
        main_layout.addWidget(channel_tabs)
        
        return tab

    def create_measurement_tab(self):
        """Create the measurement tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Mode selection group
        mode_group = QGroupBox("Measurement Mode")
        mode_layout = QHBoxLayout(mode_group)
        
        # Mode selection radio buttons
        measurement_radio = QRadioButton("Measurement")
        counter_radio = QRadioButton("Counter")
        measurement_radio.setChecked(True)
        
        # Create a button group
        mode_button_group = QButtonGroup()
        mode_button_group.addButton(measurement_radio, 1)
        mode_button_group.addButton(counter_radio, 0)
        mode_button_group.buttonClicked.connect(self.toggle_measurement_mode)
        
        mode_layout.addWidget(measurement_radio)
        mode_layout.addWidget(counter_radio)
        
        self.measurement_controls["mode_group"] = mode_button_group
        self.all_ui_controls.append(measurement_radio)
        self.all_ui_controls.append(counter_radio)
        
        layout.addWidget(mode_group)
        
        # Measurement settings group
        meas_settings_group = QGroupBox("Measurement Settings")
        meas_settings_layout = QFormLayout(meas_settings_group)
        
        # Coupling mode
        coupling_combo = QComboBox()
        coupling_combo.addItem("AC Coupling", 0)
        coupling_combo.addItem("DC Coupling", 1)
        coupling_combo.currentIndexChanged.connect(self.update_measurement_coupling)
        meas_settings_layout.addRow("Input Coupling:", coupling_combo)
        
        self.measurement_controls["coupling"] = coupling_combo
        self.all_ui_controls.append(coupling_combo)
        
        # Gate time
        gate_time = QDoubleSpinBox()
        gate_time.setRange(0.001, 10)
        gate_time.setDecimals(3)
        gate_time.setValue(0.02)
        gate_time.setSuffix(" s")
        gate_time.valueChanged.connect(self.update_gate_time)
        meas_settings_layout.addRow("Gate Time:", gate_time)
        
        self.measurement_controls["gate_time"] = gate_time
        self.all_ui_controls.append(gate_time)
        
        # Frequency range
        freq_range_combo = QComboBox()
        freq_range_combo.addItem("High Frequency (>2kHz)", 0)
        freq_range_combo.addItem("Low Frequency (<2kHz)", 1)
        freq_range_combo.currentIndexChanged.connect(self.update_freq_range)
        meas_settings_layout.addRow("Frequency Range:", freq_range_combo)
        
        self.measurement_controls["freq_range"] = freq_range_combo
        self.all_ui_controls.append(freq_range_combo)
        
        # Apply measurement settings button
        apply_meas_btn = QPushButton("Apply Measurement Settings")
        apply_meas_btn.clicked.connect(self.apply_measurement_settings)
        self.all_ui_controls.append(apply_meas_btn)
        
        meas_settings_layout.addRow("", apply_meas_btn)
        
        layout.addWidget(meas_settings_group)
        
        # Measurement results group
        results_group = QGroupBox("Measurement Results")
        results_layout = QFormLayout(results_group)
        
        # Counter result
        count_value = QLineEdit()
        count_value.setReadOnly(True)
        results_layout.addRow("Count Value:", count_value)
        self.measurement_controls["count_value"] = count_value
        
        # High frequency result
        high_freq = QLineEdit()
        high_freq.setReadOnly(True)
        results_layout.addRow("High Frequency:", high_freq)
        self.measurement_controls["high_freq"] = high_freq
        
        # Low frequency result
        low_freq = QLineEdit()
        low_freq.setReadOnly(True)
        results_layout.addRow("Low Frequency:", low_freq)
        self.measurement_controls["low_freq"] = low_freq
        
        # Positive pulse width
        pos_pulse = QLineEdit()
        pos_pulse.setReadOnly(True)
        results_layout.addRow("Positive Pulse Width:", pos_pulse)
        self.measurement_controls["pos_pulse"] = pos_pulse
        
        # Negative pulse width
        neg_pulse = QLineEdit()
        neg_pulse.setReadOnly(True)
        results_layout.addRow("Negative Pulse Width:", neg_pulse)
        self.measurement_controls["neg_pulse"] = neg_pulse
        
        # Period
        period = QLineEdit()
        period.setReadOnly(True)
        results_layout.addRow("Period:", period)
        self.measurement_controls["period"] = period
        
        # Duty cycle
        duty_cycle = QLineEdit()
        duty_cycle.setReadOnly(True)
        results_layout.addRow("Duty Cycle:", duty_cycle)
        self.measurement_controls["duty_cycle"] = duty_cycle
        
        layout.addWidget(results_group)
        
        # Request measurement update button
        update_meas_btn = QPushButton("Update Measurement Readings")
        update_meas_btn.clicked.connect(self.request_measurement_update)
        self.all_ui_controls.append(update_meas_btn)
        
        layout.addWidget(update_meas_btn)
        layout.addStretch(1)
        
        return tab

    def create_sweep_tab(self):
        """Create the sweep frequency and voltage control tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Sweep channel selection
        channel_group = QGroupBox("Sweep Channel")
        channel_layout = QHBoxLayout(channel_group)
        
        ch1_radio = QRadioButton("Channel 1")
        ch2_radio = QRadioButton("Channel 2")
        ch1_radio.setChecked(True)
        
        # Create a button group
        channel_button_group = QButtonGroup()
        channel_button_group.addButton(ch1_radio, 0)
        channel_button_group.addButton(ch2_radio, 1)
        
        channel_layout.addWidget(ch1_radio)
        channel_layout.addWidget(ch2_radio)
        
        self.sweep_controls["channel_group"] = channel_button_group
        self.all_ui_controls.append(ch1_radio)
        self.all_ui_controls.append(ch2_radio)
        
        layout.addWidget(channel_group)
        
        # Sweep mode selection
        mode_group = QGroupBox("Sweep Mode")
        mode_layout = QHBoxLayout(mode_group)
        
        freq_sweep_radio = QRadioButton("Frequency Sweep")
        voltage_control_radio = QRadioButton("Voltage Control")
        freq_sweep_radio.setChecked(True)
        
        # Create a button group
        sweep_mode_group = QButtonGroup()
        sweep_mode_group.addButton(freq_sweep_radio, 1)
        sweep_mode_group.addButton(voltage_control_radio, 0)
        sweep_mode_group.buttonClicked.connect(self.toggle_sweep_mode)
        
        mode_layout.addWidget(freq_sweep_radio)
        mode_layout.addWidget(voltage_control_radio)
        
        self.sweep_controls["mode_group"] = sweep_mode_group
        self.all_ui_controls.append(freq_sweep_radio)
        self.all_ui_controls.append(voltage_control_radio)
        
        layout.addWidget(mode_group)
        
        # Sweep settings
        sweep_settings_group = QGroupBox("Sweep Settings")
        sweep_settings_layout = QFormLayout(sweep_settings_group)
        
        # Sweep time
        sweep_time = QDoubleSpinBox()
        sweep_time.setRange(1, 640)
        sweep_time.setDecimals(2)
        sweep_time.setValue(10)
        sweep_time.setSuffix(" s")
        sweep_time.valueChanged.connect(self.update_sweep_time)
        sweep_settings_layout.addRow("Sweep Time:", sweep_time)
        
        self.sweep_controls["sweep_time"] = sweep_time
        self.all_ui_controls.append(sweep_time)
        
        # Sweep direction
        direction_combo = QComboBox()
        direction_combo.addItem("Increasing", 0)
        direction_combo.addItem("Decreasing", 1)
        direction_combo.addItem("Back and Forth", 2)
        direction_combo.currentIndexChanged.connect(self.update_sweep_direction)
        sweep_settings_layout.addRow("Sweep Direction:", direction_combo)
        
        self.sweep_controls["direction"] = direction_combo
        self.all_ui_controls.append(direction_combo)
        
        # Sweep mode
        sweep_mode_combo = QComboBox()
        sweep_mode_combo.addItem("Linear", 0)
        sweep_mode_combo.addItem("Logarithmic", 1)
        sweep_mode_combo.currentIndexChanged.connect(self.update_sweep_mode)
        sweep_settings_layout.addRow("Sweep Type:", sweep_mode_combo)
        
        self.sweep_controls["sweep_mode"] = sweep_mode_combo
        self.all_ui_controls.append(sweep_mode_combo)
        
        layout.addWidget(sweep_settings_group)
        
        # Frequency sweep settings
        freq_sweep_group = QGroupBox("Frequency Sweep Settings")
        freq_sweep_layout = QFormLayout(freq_sweep_group)
        
        # Start frequency
        start_freq = QDoubleSpinBox()
        start_freq.setRange(0, 100000)
        start_freq.setDecimals(1)
        start_freq.setValue(1000)
        start_freq.setSuffix(" Hz")
        start_freq.valueChanged.connect(self.update_start_freq)
        freq_sweep_layout.addRow("Start Frequency:", start_freq)
        
        self.sweep_controls["start_freq"] = start_freq
        self.all_ui_controls.append(start_freq)
        
        # End frequency
        end_freq = QDoubleSpinBox()
        end_freq.setRange(0, 100000)
        end_freq.setDecimals(1)
        end_freq.setValue(10000)
        end_freq.setSuffix(" Hz")
        end_freq.valueChanged.connect(self.update_end_freq)
        freq_sweep_layout.addRow("End Frequency:", end_freq)
        
        self.sweep_controls["end_freq"] = end_freq
        self.all_ui_controls.append(end_freq)
        
        layout.addWidget(freq_sweep_group)
        
        # Amplitude sweep settings
        amp_sweep_group = QGroupBox("Amplitude Sweep Settings")
        amp_sweep_layout = QFormLayout(amp_sweep_group)
        
        # Start amplitude
        start_amp = QDoubleSpinBox()
        start_amp.setRange(0, 20)
        start_amp.setDecimals(3)
        start_amp.setValue(1)
        start_amp.setSuffix(" Vpp")
        start_amp.valueChanged.connect(self.update_start_amp)
        amp_sweep_layout.addRow("Start Amplitude:", start_amp)
        
        self.sweep_controls["start_amp"] = start_amp
        self.all_ui_controls.append(start_amp)
        
        # End amplitude
        end_amp = QDoubleSpinBox()
        end_amp.setRange(0, 20)
        end_amp.setDecimals(3)
        end_amp.setValue(8)
        end_amp.setSuffix(" Vpp")
        end_amp.valueChanged.connect(self.update_end_amp)
        amp_sweep_layout.addRow("End Amplitude:", end_amp)
        
        self.sweep_controls["end_amp"] = end_amp
        self.all_ui_controls.append(end_amp)
        
        layout.addWidget(amp_sweep_group)
        
        # Duty cycle sweep settings
        duty_sweep_group = QGroupBox("Duty Cycle Sweep Settings")
        duty_sweep_layout = QFormLayout(duty_sweep_group)
        
        # Start duty cycle
        start_duty = QDoubleSpinBox()
        start_duty.setRange(0, 100)
        start_duty.setDecimals(2)
        start_duty.setValue(20)
        start_duty.setSuffix(" %")
        start_duty.valueChanged.connect(self.update_start_duty)
        duty_sweep_layout.addRow("Start Duty Cycle:", start_duty)
        
        self.sweep_controls["start_duty"] = start_duty
        self.all_ui_controls.append(start_duty)
        
        # End duty cycle
        end_duty = QDoubleSpinBox()
        end_duty.setRange(0, 100)
        end_duty.setDecimals(2)
        end_duty.setValue(80)
        end_duty.setSuffix(" %")
        end_duty.valueChanged.connect(self.update_end_duty)
        duty_sweep_layout.addRow("End Duty Cycle:", end_duty)
        
        self.sweep_controls["end_duty"] = end_duty
        self.all_ui_controls.append(end_duty)
        
        layout.addWidget(duty_sweep_group)
        
        # Apply sweep settings button
        apply_sweep_btn = QPushButton("Apply Sweep Settings")
        apply_sweep_btn.clicked.connect(self.apply_sweep_settings)
        self.all_ui_controls.append(apply_sweep_btn)
        
        layout.addWidget(apply_sweep_btn)
        layout.addStretch(1)
        
        return tab
    
    def refresh_device_status(self):
        """Request a refresh of all device settings"""
        self.message_log.setText("Refreshing device status...")
        # Use the BLE worker's query_device_status method which is now parameterized
        if self.ble_worker.loop:
            asyncio.run_coroutine_threadsafe(self.ble_worker.query_device_status(), self.ble_worker.loop)
    
    def send_manual_command(self):
        """Send a manually entered command"""
        command = self.cmd_input.text()
        if command:
            self.ble_worker.queue_command(command)
            self.cmd_input.clear()
    
    def update_parameter(self, channel, param_type, state=None):
        """Update a parameter for the specified channel"""
        if param_type == "output":
            # Handle the special case for output which needs both channels
            ch1_state = "1" if (channel == 1 and state == Qt.Checked) or \
                          (channel == 2 and self.channel_controls[1]["enable"].isChecked()) else "0"
            ch2_state = "1" if (channel == 2 and state == Qt.Checked) or \
                          (channel == 1 and self.channel_controls[2]["enable"].isChecked()) else "0"
            self.ble_worker.queue_command(f":w10={ch1_state},{ch2_state}.")
            return
        
        # Handle other parameters with parameterized command generation
        if param_type == "waveform":
            waveform_idx = WAVEFORMS[self.channel_controls[channel]["waveform"].currentText()]
            value = f"{waveform_idx}."
            
        elif param_type == "frequency":
            value = self.channel_controls[channel]["frequency"].value()
            unit_idx = FREQ_UNITS[self.channel_controls[channel]["freq_unit"].currentText()]
            value = f"{int(value*1000)},{unit_idx}."
            
        elif param_type == "amplitude":
            value = self.channel_controls[channel]["amplitude"].value()
            value = f"{int(value*1000)}."
            
        elif param_type == "offset":
            value = self.channel_controls[channel]["offset"].value()
            if value == 0:
                offset_value = 1000
            else:
                offset_value = int(1000 + value * 100)
            value = f"{offset_value}."
            
        elif param_type == "duty":
            value = self.channel_controls[channel]["duty"].value()
            value = f"{int(value*100)}."
            
        elif param_type == "phase":
            value = self.channel_controls[channel]["phase"].value()
            value = f"{int(value*100)}."
        
        # Generate command based on parameter type and channel
        if param_type in ["waveform", "frequency", "amplitude", "offset"]:
            # These use w1x format with different offsets
            cmd_num = channel + PARAM_OFFSETS[param_type]
            cmd = f"w1{cmd_num}"
        elif param_type == "duty":
            # Special handling for duty cycle (commands 19, 20)
            cmd = f"w{18 + channel}"
        elif param_type == "phase":
            # These use w2x format
            cmd = f"w2{channel}"
        
        self.ble_worker.queue_command(f":{cmd}={value}")
        
    def apply_all_settings(self, channel):
        """Apply all settings for the specified channel"""
        for param in ["waveform", "frequency", "amplitude", "offset", "duty", "phase"]:
            self.update_parameter(channel, param)
        # Update output state last
        self.update_parameter(channel, "output", self.channel_controls[channel]["enable"].checkState())
    
    # Modulation functions
    def update_modulation_type(self, channel, index):
        """Update modulation type for the specified channel"""
        type_value = index  # Index matches MODULATION_TYPES values
        other_channel = 2 if channel == 1 else 1
        other_value = self.modulation_controls[other_channel]["type"].currentIndex()
        self.ble_worker.queue_command(f":w40={type_value},{other_value}.")
        
    def update_modulation_source(self, channel, index):
        """Update modulation source for the specified channel"""
        source_value = index  # Index matches MODULATION_SOURCES values
        other_channel = 2 if channel == 1 else 1
        other_value = self.modulation_controls[other_channel]["source"].currentIndex()
        self.ble_worker.queue_command(f":w42={source_value},{other_value}.")
        
    def update_modulation_wave(self, channel, index):
        """Update modulation wave type for the specified channel"""
        wave_value = index  # Index matches MODULATION_WAVES values
        other_channel = 2 if channel == 1 else 1
        other_value = self.modulation_controls[other_channel]["wave"].currentIndex()
        self.ble_worker.queue_command(f":w41={wave_value},{other_value}.")
        
    def update_modulation_frequency(self, channel, value):
        """Update modulation frequency for the specified channel"""
        freq_value = int(value * 1000)  # Convert to mHz for device
        cmd = f"w{42 + channel}"  # w43 for CH1, w44 for CH2
        self.ble_worker.queue_command(f":{cmd}={freq_value}.")
        
    def update_am_depth(self, channel, value):
        """Update AM modulation depth for the specified channel"""
        depth_value = int(value * 10)  # Convert to tenths of a percent
        cmd = f"w{44 + channel}"  # w45 for CH1, w46 for CH2
        self.ble_worker.queue_command(f":{cmd}={depth_value}.")
        
    def update_fm_deviation(self, channel, value):
        """Update FM frequency deviation for the specified channel"""
        dev_value = int(value * 10)  # Convert to tenths of Hz
        cmd = f"w{46 + channel}"  # w47 for CH1, w48 for CH2
        self.ble_worker.queue_command(f":{cmd}={dev_value}.")
        
    def update_fsk_hopping(self, channel, value):
        """Update FSK hopping frequency for the specified channel"""
        hop_value = int(value * 10)  # Convert to tenths of Hz
        cmd = f"w{48 + channel}"  # w49 for CH1, w50 for CH2
        self.ble_worker.queue_command(f":{cmd}={hop_value}.")
        
    def update_pm_phase(self, channel, value):
        """Update PM phase deviation for the specified channel"""
        phase_value = int(value * 10)  # Convert to tenths of a degree
        cmd = f"w{50 + channel}"  # w51 for CH1, w52 for CH2
        self.ble_worker.queue_command(f":{cmd}={phase_value}.")
        
    def update_pulse_width(self, channel, value):
        """Update pulse width for the specified channel"""
        width_value = int(value * 1000)  # Convert to nanoseconds
        cmd = f"w{52 + channel}"  # w53 for CH1, w54 for CH2
        self.ble_worker.queue_command(f":{cmd}={width_value}.")
        
    def update_pulse_period(self, channel, value):
        """Update pulse period for the specified channel"""
        period_value = int(value * 100)  # Convert to hundredths of microseconds
        cmd = f"w{54 + channel}"  # w55 for CH1, w56 for CH2
        self.ble_worker.queue_command(f":{cmd}={period_value}.")
        
    def update_pulse_inversion(self, channel, value):
        """Update pulse wave inversion for the specified channel"""
        inversion_value = value  # 0 for Normal, 1 for Inversion
        other_channel = 2 if channel == 1 else 1
        other_value = self.modulation_controls[other_channel]["pulse_inversion"].currentIndex()
        self.ble_worker.queue_command(f":w57={inversion_value},{other_value}.")
        
    def update_burst_idle(self, channel, value):
        """Update burst wave idle mode for the specified channel"""
        idle_value = value  # 0 for Zero, 1 for Positive max, 2 for Negative max
        other_channel = 2 if channel == 1 else 1
        other_value = self.modulation_controls[other_channel]["burst_idle"].currentIndex()
        self.ble_worker.queue_command(f":w58={idle_value},{other_value}.")
        
    def update_polarity(self, channel, value):
        """Update signal polarity for the specified channel"""
        polarity_value = value  # 0 for Positive, 1 for Negative
        other_channel = 2 if channel == 1 else 1
        other_value = self.modulation_controls[other_channel]["polarity"].currentIndex()
        self.ble_worker.queue_command(f":w59={polarity_value},{other_value}.")
        
    def update_trigger_source(self, channel, value):
        """Update trigger source for the specified channel"""
        trigger_value = value  # 0 for Key, 1 for Internal, 2 for External AC, 3 for External DC
        other_channel = 2 if channel == 1 else 1
        other_value = self.modulation_controls[other_channel]["trigger_source"].currentIndex()
        self.ble_worker.queue_command(f":w60={trigger_value},{other_value}.")
        
    def update_burst_count(self, channel, value):
        """Update burst pulse count for the specified channel"""
        count_value = value
        other_channel = 2 if channel == 1 else 1
        other_value = self.modulation_controls[other_channel]["burst_count"].value()
        self.ble_worker.queue_command(f":w61={count_value},{other_value}.")
        
    def apply_modulation_settings(self, channel):
        """Apply all modulation settings for the specified channel"""
        # Update modulation type and source
        self.update_modulation_type(channel, self.modulation_controls[channel]["type"].currentIndex())
        self.update_modulation_source(channel, self.modulation_controls[channel]["source"].currentIndex())
        
        # Update wave type and frequency
        self.update_modulation_wave(channel, self.modulation_controls[channel]["wave"].currentIndex())
        self.update_modulation_frequency(channel, self.modulation_controls[channel]["frequency"].value())
        
        # Update parameter values based on modulation type
        mod_type = self.modulation_controls[channel]["type"].currentIndex()
        
        # AM
        if mod_type == 0:  # AM
            self.update_am_depth(channel, self.modulation_controls[channel]["am_depth"].value())
        
        # FM
        elif mod_type == 1:  # FM
            self.update_fm_deviation(channel, self.modulation_controls[channel]["fm_deviation"].value())
        
        # PM
        elif mod_type == 2:  # PM
            self.update_pm_phase(channel, self.modulation_controls[channel]["pm_phase"].value())
        
        # FSK
        elif mod_type == 4:  # FSK
            self.update_fsk_hopping(channel, self.modulation_controls[channel]["fsk_hopping"].value())
        
        # PULSE
        elif mod_type == 6:  # PULSE
            self.update_pulse_width(channel, self.modulation_controls[channel]["pulse_width"].value())
            self.update_pulse_period(channel, self.modulation_controls[channel]["pulse_period"].value())
            self.update_pulse_inversion(channel, self.modulation_controls[channel]["pulse_inversion"].currentIndex())
        
        # BURST
        elif mod_type == 7:  # BURST
            self.update_burst_count(channel, self.modulation_controls[channel]["burst_count"].value())
            self.update_burst_idle(channel, self.modulation_controls[channel]["burst_idle"].currentIndex())
        
        # Update common settings
        self.update_polarity(channel, self.modulation_controls[channel]["polarity"].currentIndex())
        self.update_trigger_source(channel, self.modulation_controls[channel]["trigger_source"].currentIndex())

    # Measurement functions
    def toggle_measurement_mode(self, button):
        """Toggle between measurement and counter modes"""
        mode = self.measurement_controls["mode_group"].checkedId()
        self.ble_worker.queue_command(f":w63={mode}.")
        
    def update_measurement_coupling(self, index):
        """Update measurement coupling mode"""
        coupling = self.measurement_controls["coupling"].currentIndex()
        gate_time = int(self.measurement_controls["gate_time"].value() * 1000)  # Convert to ms
        freq_range = self.measurement_controls["freq_range"].currentIndex()
        self.ble_worker.queue_command(f":w62={coupling},{gate_time},{freq_range}.")
        
    def update_gate_time(self, value):
        """Update measurement gate time"""
        self.update_measurement_coupling(0)  # Reuse function to update all measurement params
        
    def update_freq_range(self, index):
        """Update frequency range setting"""
        self.update_measurement_coupling(0)  # Reuse function to update all measurement params
        
    def apply_measurement_settings(self):
        """Apply all measurement settings"""
        # Set measurement mode
        mode = self.measurement_controls["mode_group"].checkedId()
        self.ble_worker.queue_command(f":w63={mode}.")
        
        # Set measurement parameters
        self.update_measurement_coupling(0)
        
    def request_measurement_update(self):
        """Request update of measurement readings"""
        # Query measurement readings
        for cmd in range(80, 87):
            self.ble_worker.queue_command(f":r{cmd}=0.")
            
    def update_measurement_display(self, data):
        """Update measurement display with received data"""
        if 'count' in data:
            self.measurement_controls["count_value"].setText(f"{data['count']}")
            
        if 'high_freq' in data:
            self.measurement_controls["high_freq"].setText(f"{data['high_freq']:.3f} Hz")
            
        if 'low_freq' in data:
            self.measurement_controls["low_freq"].setText(f"{data['low_freq']:.3f} Hz")
            
        if 'pos_pulse_width' in data:
            self.measurement_controls["pos_pulse"].setText(f"{data['pos_pulse_width']:.3f} μs")
            
        if 'neg_pulse_width' in data:
            self.measurement_controls["neg_pulse"].setText(f"{data['neg_pulse_width']:.3f} μs")
            
        if 'period' in data:
            self.measurement_controls["period"].setText(f"{data['period']:.2f} μs")
            
        if 'duty_cycle' in data:
            self.measurement_controls["duty_cycle"].setText(f"{data['duty_cycle']:.2f} %")

    # Sweep functions
    def toggle_sweep_mode(self, button):
        """Toggle between frequency sweep and voltage control modes"""
        channel = self.sweep_controls["channel_group"].checkedId()
        mode = self.sweep_controls["mode_group"].checkedId()
        self.ble_worker.queue_command(f":w65={mode},{1-mode}.")  # Only one mode can be active at a time
        
    def update_sweep_time(self):
        """Update sweep time setting"""
        sweep_time = int(self.sweep_controls["sweep_time"].value() * 100)  # Convert to hundredths of a second
        channel = self.sweep_controls["channel_group"].checkedId()
        direction = self.sweep_controls["direction"].currentIndex()
        sweep_mode = self.sweep_controls["sweep_mode"].currentIndex()
        self.ble_worker.queue_command(f":w64={channel},{sweep_time},{direction},{sweep_mode}.")
        
    def update_sweep_direction(self, index):
        """Update sweep direction setting"""
        self.update_sweep_time()  # Reuse function to update all sweep params
        
    def update_sweep_mode(self, index):
        """Update sweep mode setting (linear/logarithmic)"""
        self.update_sweep_time()  # Reuse function to update all sweep params
        
    def update_start_freq(self, value):
        """Update start frequency for frequency sweep"""
        freq_value = int(value * 10)  # Convert to tenths of Hz
        self.ble_worker.queue_command(f":w66={freq_value}.")
        
    def update_end_freq(self, value):
        """Update end frequency for frequency sweep"""
        freq_value = int(value * 10)  # Convert to tenths of Hz
        self.ble_worker.queue_command(f":w67={freq_value}.")
        
    def update_start_amp(self, value):
        """Update start amplitude for amplitude sweep"""
        amp_value = int(value * 1000)  # Convert to mV
        self.ble_worker.queue_command(f":w68={amp_value}.")
        
    def update_end_amp(self, value):
        """Update end amplitude for amplitude sweep"""
        amp_value = int(value * 1000)  # Convert to mV
        self.ble_worker.queue_command(f":w69={amp_value}.")
        
    def update_start_duty(self, value):
        """Update start duty cycle for duty cycle sweep"""
        duty_value = int(value * 100)  # Convert to hundredths of a percent
        self.ble_worker.queue_command(f":w70={duty_value}.")
        
    def update_end_duty(self, value):
        """Update end duty cycle for duty cycle sweep"""
        duty_value = int(value * 100)  # Convert to hundredths of a percent
        self.ble_worker.queue_command(f":w71={duty_value}.")
        
    def apply_sweep_settings(self):
        """Apply all sweep settings"""
        # Set sweep mode
        self.toggle_sweep_mode(None)
        
        # Set sweep parameters
        self.update_sweep_time()
        
        # Set sweep range
        self.update_start_freq(self.sweep_controls["start_freq"].value())
        self.update_end_freq(self.sweep_controls["end_freq"].value())
        self.update_start_amp(self.sweep_controls["start_amp"].value())
        self.update_end_amp(self.sweep_controls["end_amp"].value())
        self.update_start_duty(self.sweep_controls["start_duty"].value())
        self.update_end_duty(self.sweep_controls["end_duty"].value())
        
    def on_refresh_started(self):
        """Handle refresh start event by disabling UI controls"""
        # Show progress bar
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        # Disable all UI controls to prevent interaction during refresh
        for control in self.all_ui_controls:
            control.setEnabled(False)
        self.message_log.setText("Refreshing device status - UI temporarily disabled")
        
    def on_refresh_completed(self):
        """Handle refresh completion event by re-enabling UI controls"""
        # Hide progress bar
        self.progress_bar.setVisible(False)
        # Re-enable all UI controls
        for control in self.all_ui_controls:
            control.setEnabled(True)
        self.message_log.setText("Refresh completed - UI re-enabled")
        
    def update_refresh_progress(self, current, total):
        """Update progress bar during refresh operation"""
        progress_percentage = int((current / total) * 100)
        self.progress_bar.setValue(progress_percentage)
        self.message_log.setText(f"Refreshing device status: {current}/{total} commands")
    
    @pyqtSlot(bool)
    def update_connection_status(self, connected):
        """Update connection status display"""
        if connected:
            self.connection_status.setText("Connected")
            self.connection_status.setStyleSheet("color: green")
        else:
            self.connection_status.setText("Disconnected")
            self.connection_status.setStyleSheet("color: red")
    
    @pyqtSlot(str)
    def update_message_log(self, message):
        """Update command log display"""
        self.message_log.setText(message)
    
    @pyqtSlot(str)
    def update_notification_log(self, message):
        """Update notification log display"""
        self.notification_log.setText(message)
    
    @pyqtSlot(dict)
    def update_ui_from_status(self, status):
        """Update UI controls based on received device status"""
        # Update UI elements with received status values
        if 'ch1_output' in status:
            self.channel_controls[1]["enable"].setChecked(status['ch1_output'])
            
        if 'ch2_output' in status:
            self.channel_controls[2]["enable"].setChecked(status['ch2_output'])
        
        for channel in [1, 2]:
            ch_prefix = f"ch{channel}_"
            
            if f'{ch_prefix}waveform' in status:
                waveform_value = status[f'{ch_prefix}waveform']
                # Find the corresponding waveform name
                for name, value in WAVEFORMS.items():
                    if value == waveform_value:
                        index = self.channel_controls[channel]["waveform"].findText(name)
                        if index >= 0:
                            self.channel_controls[channel]["waveform"].setCurrentIndex(index)
                        break
            
            if f'{ch_prefix}frequency' in status and f'{ch_prefix}freq_unit' in status:
                self.channel_controls[channel]["frequency"].setValue(status[f'{ch_prefix}frequency'])
                self.channel_controls[channel]["freq_unit"].setCurrentIndex(status[f'{ch_prefix}freq_unit'])
                
            if f'{ch_prefix}amplitude' in status:
                self.channel_controls[channel]["amplitude"].setValue(status[f'{ch_prefix}amplitude'])
                
            if f'{ch_prefix}offset' in status:
                self.channel_controls[channel]["offset"].setValue(status[f'{ch_prefix}offset'])
                
            if f'{ch_prefix}duty' in status:
                self.channel_controls[channel]["duty"].setValue(status[f'{ch_prefix}duty'])
                
            if f'{ch_prefix}phase' in status:
                self.channel_controls[channel]["phase"].setValue(status[f'{ch_prefix}phase'])
                
            # Update modulation controls if available
            if f'{ch_prefix}mod_type' in status and channel in self.modulation_controls:
                self.modulation_controls[channel]["type"].setCurrentIndex(status[f'{ch_prefix}mod_type'])
                
            if f'{ch_prefix}mod_source' in status and channel in self.modulation_controls:
                self.modulation_controls[channel]["source"].setCurrentIndex(status[f'{ch_prefix}mod_source'])
                
            if f'{ch_prefix}mod_wave' in status and channel in self.modulation_controls:
                self.modulation_controls[channel]["wave"].setCurrentIndex(status[f'{ch_prefix}mod_wave'])
                
            if f'{ch_prefix}mod_freq' in status and channel in self.modulation_controls:
                self.modulation_controls[channel]["frequency"].setValue(status[f'{ch_prefix}mod_freq'])
                
            if f'{ch_prefix}am_depth' in status and channel in self.modulation_controls:
                self.modulation_controls[channel]["am_depth"].setValue(status[f'{ch_prefix}am_depth'])
                
            if f'{ch_prefix}fm_deviation' in status and channel in self.modulation_controls:
                self.modulation_controls[channel]["fm_deviation"].setValue(status[f'{ch_prefix}fm_deviation'])
                
            if f'{ch_prefix}pm_phase' in status and channel in self.modulation_controls:
                self.modulation_controls[channel]["pm_phase"].setValue(status[f'{ch_prefix}pm_phase'])
                
            if f'{ch_prefix}fsk_hopping' in status and channel in self.modulation_controls:
                self.modulation_controls[channel]["fsk_hopping"].setValue(status[f'{ch_prefix}fsk_hopping'])
                
            if f'{ch_prefix}pulse_width' in status and channel in self.modulation_controls:
                self.modulation_controls[channel]["pulse_width"].setValue(status[f'{ch_prefix}pulse_width'])
                
            if f'{ch_prefix}pulse_period' in status and channel in self.modulation_controls:
                self.modulation_controls[channel]["pulse_period"].setValue(status[f'{ch_prefix}pulse_period'])
                
            if f'{ch_prefix}pulse_inversion' in status and channel in self.modulation_controls:
                self.modulation_controls[channel]["pulse_inversion"].setCurrentIndex(status[f'{ch_prefix}pulse_inversion'])
                
            if f'{ch_prefix}burst_idle' in status and channel in self.modulation_controls:
                self.modulation_controls[channel]["burst_idle"].setCurrentIndex(status[f'{ch_prefix}burst_idle'])
                
            if f'{ch_prefix}polarity' in status and channel in self.modulation_controls:
                self.modulation_controls[channel]["polarity"].setCurrentIndex(status[f'{ch_prefix}polarity'])
                
            if f'{ch_prefix}trigger_source' in status and channel in self.modulation_controls:
                self.modulation_controls[channel]["trigger_source"].setCurrentIndex(status[f'{ch_prefix}trigger_source'])
                
            if f'{ch_prefix}burst_count' in status and channel in self.modulation_controls:
                self.modulation_controls[channel]["burst_count"].setValue(status[f'{ch_prefix}burst_count'])
                
    def closeEvent(self, event):
        # Clean up BLE worker thread
        self.ble_worker.stop()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    ui = SignalGeneratorUI()
    ui.show()
    sys.exit(app.exec_())
