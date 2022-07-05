# Support for filament width sensor
#
# Copyright (C) 2019  Mustafa YILDIZ <mydiz@hotmail.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
from . import filament_switch_sensor

ADC_REPORT_TIME = 0.500
ADC_SAMPLE_TIME = 0.03
ADC_SAMPLE_COUNT = 15

class InFiDEL:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.pin = config.get('pin')
        self.lookUpTable= config.getlists('lookup_table', parser=float, 
                                          seps=(',','\n'))
        # Look up table for calibration with {Raw value,  real diameter} format
        # RAW 1000, diameter 1.
        # RAW 2000, diameter 2.
        self.MEASUREMENT_INTERVAL_MM=config.getint('measurement_interval',10)
        self.nominal_filament_dia = config.getfloat(
            'default_nominal_filament_diameter', above=1, default=1.75)
        self.measurement_delay = config.getfloat('measurement_delay', above=0.)
        self.measurement_max_difference = config.getfloat('max_difference', 0.5)
        self.max_diameter = (self.nominal_filament_dia
                             + self.measurement_max_difference)
        self.min_diameter = (self.nominal_filament_dia
                             - self.measurement_max_difference)
        self.diameter =self.nominal_filament_dia
        self.is_active =config.getboolean('enable', False)
        self.runout_dia=config.getfloat('min_diameter', 1.0)
        self.is_log =config.getboolean('logging', False)
        # filament array [position, filamentWidth]
        self.filament_array = []
        self.lastFilamentWidthReading = 0
        self.filament_width = self.nominal_filament_dia
        # printer objects
        self.toolhead = self.ppins = self.mcu_adc = None
        self.printer.register_event_handler("klippy:ready", self.handle_ready)
        # Start adc
        self.ppins = self.printer.lookup_object('pins')
        self.mcu_adc = self.ppins.setup_pin('adc', self.pin)
        self.mcu_adc.setup_minmax(ADC_SAMPLE_TIME, ADC_SAMPLE_COUNT)
        self.mcu_adc.setup_adc_callback(ADC_REPORT_TIME, self.adc_callback)
        # extrude factor updating
        self.extrude_factor_update_timer = self.reactor.register_timer(
            self.extrude_factor_update_event)
        # Register commands
        self.gcode = self.printer.lookup_object('gcode')
        self.gcode.register_command('QUERY_FILAMENT_WIDTH', self.cmd_M407)
        self.gcode.register_command('RESET_FILAMENT_WIDTH_SENSOR',
                                    self.cmd_ClearFilamentArray)
        self.gcode.register_command('DISABLE_FILAMENT_WIDTH_SENSOR',
                                    self.cmd_M406)
        self.gcode.register_command('ENABLE_FILAMENT_WIDTH_SENSOR',
                                    self.cmd_M405)
        self.gcode.register_command('QUERY_RAW_FILAMENT_WIDTH',
                                    self.cmd_Get_Raw_Values)
        self.gcode.register_command('ENABLE_FILAMENT_WIDTH_LOG',
                                    self.cmd_log_enable)
        self.gcode.register_command('DISABLE_FILAMENT_WIDTH_LOG',
                                    self.cmd_log_disable)

        self.runout_helper = filament_switch_sensor.RunoutHelper(config)
    # Initialization
    def handle_ready(self):
        # Load printer objects
        self.toolhead = self.printer.lookup_object('toolhead')

        # Start extrude factor update timer
        self.reactor.update_timer(self.extrude_factor_update_timer,
                                  self.reactor.NOW)

    def adc_callback(self, read_time, read_value):
        # read sensor value
        self.lastFilamentWidthReading = round(read_value * 10000)
        self.diameter = round(self._calcDiameter(), 3)

    def _calcDiameter(self):
        lastReading = self.lastFilamentWidthReading
        table = self.lookUpTable
        dia = 0
        for i, entry in enumerate(table[1:]):
            if entry[0] > lastReading and lastReading > table[i][0]:
                dia = (((entry[1] - table[i][1]) / (entry[0] - table[i][0])) *
                        (lastReading - table[i][0]) + table[i][1])
        return dia

    def _update_filament_array(self, last_epos):
        # Fill array
        if len(self.filament_array) > 0:
            # Get last reading position in array & calculate next
            # reading position
          next_reading_position = (self.filament_array[-1][0] +
          self.MEASUREMENT_INTERVAL_MM)
          if next_reading_position <= (last_epos + self.measurement_delay):
            self.filament_array.append([last_epos + self.measurement_delay,
                                            self.diameter])
            if self.is_log:
                 self.gcode.respond_info("Filament width:%.3f" %
                                         ( self.diameter ))
        else:
            # add first item to array
            self.filament_array.append([self.measurement_delay + last_epos,
                                        self.diameter])
            self.firstExtruderUpdatePosition = (self.measurement_delay
                                                + last_epos)

    def extrude_factor_update_event(self, eventtime):
        # Update extrude factor
        pos = self.toolhead.get_position()
        last_epos = pos[3]
        # Update filament array for lastFilamentWidthReading
        self.update_filament_array(last_epos)
        # Check runout
        self.runout_helper.note_filament_present(
            self.diameter > self.runout_dia)
        # Does filament exists
        if self.diameter > 0.5:
            if len(self.filament_array) > 0:
                # Get first position in filament array
                pending_position = self.filament_array[0][0]
                if pending_position <= last_epos:
                    # Get first item in filament_array queue
                    item = self.filament_array.pop(0)
                    self.filament_width = item[1]
                else:
                    self.filament_width = self.nominal_filament_dia
                if (self.min_diameter <= self.filament_width
                    <= self.max_diameter):
                    percentage = round(self.nominal_filament_dia**2
                                       / self.filament_width**2 * 100)
                    self.gcode.run_script("M221 S" + str(percentage))
                else:
                    self.gcode.run_script("M221 S100")
        else:
            self.gcode.run_script("M221 S100")
            self.filament_array = []

        if self.is_active:
            return eventtime + 1
        else:
            return self.reactor.NEVER

    def cmd_M407(self, gcmd):
        response = ""
        if self.diameter > 0:
            response += ("Filament dia (measured mm): "
                         + str(self.diameter))
        else:
            response += "Filament NOT present"
        gcmd.respond_info(response)

    def cmd_ClearFilamentArray(self, gcmd):
        self.filament_array = []
        gcmd.respond_info("Filament width measurements cleared!")
        # Set extrude multiplier to 100%
        self.gcode.run_script_from_command("M221 S100")

    def cmd_M405(self, gcmd):
        response = "Filament width sensor Turned On"
        if self.is_active:
            response = "Filament width sensor is already On"
        else:
            self.is_active = True
            # Start extrude factor update timer
            self.reactor.update_timer(self.extrude_factor_update_timer,
                                      self.reactor.NOW)
        gcmd.respond_info(response)

    def cmd_M406(self, gcmd):
        response = "Filament width sensor Turned Off"
        if not self.is_active:
            response = "Filament width sensor is already Off"
        else:
            self.is_active = False
            # Stop extrude factor update timer
            self.reactor.update_timer(self.extrude_factor_update_timer,
                                      self.reactor.NEVER)
            # Clear filament array
            self.filament_array = []
            # Set extrude multiplier to 100%
            self.gcode.run_script_from_command("M221 S100")
        gcmd.respond_info(response)

    def cmd_Get_Raw_Values(self, gcmd):
        response = "Diameter="
        response +=  (" "+str(self.diameter))
        response +=  (" RAW="+ str(self.lastFilamentWidthReading))
        gcmd.respond_info(response)

    def get_status(self, eventtime):
        return {'Diameter': self.diameter,
                'Raw':self.lastFilamentWidthReading,
                'current_width' : self.filament_width,
                'is_active':self.is_active}

    def cmd_log_enable(self, gcmd):
        self.is_log = True
        gcmd.respond_info("Filament width logging Turned On")

    def cmd_log_disable(self, gcmd):
        self.is_log = False
        gcmd.respond_info("Filament width logging Turned Off")

def load_config(config):
    return InFiDEL(config)
