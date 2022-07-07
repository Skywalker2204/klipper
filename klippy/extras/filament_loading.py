#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Jul  6 23:38:29 2022

@author: lukashentschel
"""

class FilamentLoading:
    
    LONG_MOVE_THRESHOLD= 70.
    
    def __init__(self, config):
        self.config = config
        self.name = config.get_name().split()[-1]
        self.printer=config.get_printer()
        self.reactor=config.get_reactor()
        self.printer.register_event_handler("klippy:connect",
                                            self.handle_connect)
        
        self.loader_stepper = config.get('loader_stepper')
        self.toolhead_sensor_name = config.get('toolhead_sensor')
        self.loader_sensor_name = config.get('toolhead_sensor', None)
        
        self.length = config.getfloat('loader_distance', 500.)
        self.extrude = config.getflaot('extruder_distance', 150.)
        
        # Minor Parameters
        self.long_moves_speed = config.getfloat('long_moves_speed', 40.)
        self.long_moves_accel = config.getfloat('long_moves_accel', 400.)
        self.short_moves_speed = config.getfloat('short_moves_speed', 5.)
        self.short_moves_accel = config.getfloat('short_moves_accel', 400.)
        
        self.gcode = self.printer.lookup_object('gcode')
        self.gcode.register_mux_command("LOAD_FILAMENT", "EXTRUDER", 
                                        self.name, self.cmd_LOAD_FILAMENT)
        self.gcode.register_mux_command("UNLOAD_FILAMENT", "EXTRUDER", 
                                        self.name, self.cmd_UNLOAD_FILAMENT)
        
    def handle_connect(self):
        self.toohead = self.lookup_object('toolhead')
            
    def get_status(self, eventtime):
        return {}
    
    def _extruder_stepper_move_wait(self, dist):
        speed = self.long_moves_speed
        accel = self.long_moves_accel
        if dist < self.LONG_MOVE_THRESHOLD:
            speed = self.short_moves_speed
            accel = self.short_moves_accel
        command_string = ('FORCE_MOVE STEPPER="%s" DISTANCE=%s'
                         ' VELOCITY=%s ACCEL=%s'
                         % (self.loader_stepper, dist, speed, accel))
        self.gcode.run_script_from_command(command_string)
        
    def _check_sensor(self, sensor_name):
        sensor = self.printer.lookup_object("filament_switch_sensor "+
                                            sensor_name)
        return bool(self.toolhead_sensor.runout_helper.filament_present)
    
    def _load_toolhead(self, num_retry=3):      
        if (self.loader_sensor_name and 
           not self._check_sensor(self.loader_sensor_name)):
            self.gcode._respond_error('No filament detected!')
            return False
        self._extruder_stepper_move_wait(self.length)
        self.toolhead.wait_moves()
        for i in range(num_retry):
            if self._check_sensor(self.toolhead_sensor_name):
                self.gcode.respond_info('Filament loaded to toolhead')
                return True
            self._extruder_stepper_move_wait(20)
        
        self.gcode.respond_info('Filament not laoded to toolhead')
        self._extruder_stepper_move_wait(-self.length)
        return False
    
    def _load_to_nozzle(self):
        speeds = [500, 250]
        dist = round(self.extrude/len(speeds), 2)
        for sp in speeds:
            self.gcode.run_script_from_command(
                "G1 E{:.2f} F{:.2f}".format(dist, sp))
            self.toolhead.wait_moves()
            
    def _unload_filament(self, num_retry):
        if (self.loader_sensor_name and 
           not self._check_sensor(self.loader_sensor_name)):
            self.gcode._respond_error('No filament detected!')
            return False
        i = 0
        while self._check_sensor(self.toolhead_sensor_name):
            try:
                self.gcode.run_script_from_command(
                    "G1 E{:.2f} F500".format(self.extrude))
                self.toolhead.wait_moves()
            except:
                self.gcode._respond_error('Prevent Cold Extrusion')
            if i >= num_retry:
                self.gcode._respond_error("Filament stuck, unable to unload!")
                return False
        
        self._extruder_stepper_move_wait(self.length)
        self.toolhead.wait_moves()
        return True
            
    def cmd_LOAD_TO_NOZZLE(self, gcmd):
        num = gcmd.get_int('RETRY', 3)
        ext = gcmd.get('EXTRUDER')
        self.gcode.respond_info('Extruder =' + ext)
        if self._load_toolhead():
            try:
                self._load_to_nozzle(num)
                self.gcode.respond_info('Filament loading succesfull')
            except:
                self.gcode.respond_info(
                    'No cold Extrusion, heat up extruder and finish loading manual')  
                
    def cmd_UNLOAD_FILAMENT(self, gcmd):
        num = gcmd.get_int('RETRY', 3)
        if self._unload_filament(num):
            self.gcode.respond_info('Filament unloading succesfull')
               