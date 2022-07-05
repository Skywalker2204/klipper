"""
Created on Wed Mar  9 06:09:12 2022

@author: lukashentschel

No warrenty project is still under development
"""
from . import bus
import logging, struct
######################################################################
# CommHelper Arudino HX711 
######################################################################

REPORT_TIME = 0.200

HX711_SCALE = 18 #Don't needed if values are processed
HX711_MULT = 0.25 #Don't needed if values are processed
HX711_ADDR = 0x08
HX711_TARE = 0x0A

DEBUG = True

class Arduino_i2c:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.name = config.get_name().split()[-1]
        self.i2c = bus.MCU_I2C_from_config(config, default_addr=HX711_ADDR,
                default_speed=100000)
        self.mcu = self.i2c.get_mcu()

        #read the config values
        self.report_time = config.getfloat('REPORT_TIME', REPORT_TIME, 
                                            minval=0.1) #for 10 Hz
        self.is_active = config.getboolean('IS_ACTIVE', False) 
        # Load HX711 Arduino Class
        self.timer = None
        #init local variables
        self.force = self.read_time= 0.
        self.printer.register_event_handler("klippy:ready",
                                            self._handle_ready)

        #register commands for GCode
        self.gcode = self.printer.lookup_object('gcode')
        self.gcode.register_command('LOAD_CELL_TARE', self.cmd_tare)
        self.gcode.register_command('LOAD_CELL_ENABLE', 
                                    self.cmd_load_cell_enable)
        self.gcode.register_command('LOAD_CELL_DISABLE', 
                                    self.cmd_load_cell_disable)

    def _handle_ready(self):
        if self.is_active:
            waketime = self.reactor.NOW+self.report_time
        else:
            waketime = self.reactor.NEVER
        self.timer = self.reactor.register_timer(self._update_value,
                                        waketime)

    def _update_value(self, eventtime):
        try:
            read = self.i2c.i2c_read([HX711_ADDR],4)
            self.force = struct.unpack('<f', bytearray(read['response']))[0]
            self.read_time = eventtime
        except Exception as e:
            self.gcode.respond_info(str(e))
        return eventtime + self.report_time
             
    def cmd_tare(self, gcmd):
        try:
            self.i2c.i2c_write([HX711_TARE])
            self.gcode.respond_info("Tare!!")
        except Exception as e:

                self.gcode.respond_info("Tare did not work due to " + str(e))
        
    def cmd_load_cell_enable(self, gcmd):
        self.is_active = True
        self.reactor.update_timer(self.timer, self.reactor.NOW)
        
    def cmd_load_cell_disable(self, gcmd):
        self.is_active = False
        self.reactor.update_timer(self.timer, self.reactor.NEVER)
        
    def get_status(self, eventtime):
        return {'force' : self.force,
                'is_active' : self.is_active}
        
def load_config_prefix(config):
    return Arduino_i2c(config)         
