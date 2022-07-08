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
        self.reactor=self.printer.get_reactor()
        self.printer.register_event_handler("klippy:connect",
                                            self.handle_connect)
        
        self.loader_stepper = config.get('loader_stepper')
        self.toolhead_sensor_name = config.get('toolhead_sensor')
        self.loader_sensor_name = config.get('loader_sensor', None)
        
        self.length = config.getfloat('loader_distance', 500.)
        self.extrude = config.getfloat('extruder_distance', 150.)
        
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
        self.toohead = self.printer.lookup_object('toolhead')
            
    def get_status(self, eventtime):
        return {}
    
    def _extruder_stepper_move_wait(self, dist):
        speed = self.long_moves_speed
        accel = self.long_moves_accel
        if dist < self.LONG_MOVE_THRESHOLD:
            speed = self.short_moves_speed
            accel = self.short_moves_accel
        self.gcode.respond_info("Force Move")
        command_string = ('FORCE_MOVE STEPPER="{}" '\
                          'DISTANCE={:.2f} VELOCITY={:.2f} '\
                              'ACCEL={:.2f}'.format(self.loader_stepper, 
                                                    dist, speed, accel))
        self.gcode.run_script_from_command(command_string)
        
    def _check_sensor(self, sensor_name):
        sensor = self.printer.lookup_object("filament_switch_sensor "+
                                            sensor_name)
        self.gcode.respond_info("check Sensor")
        return bool(sensor.runout_helper.filament_present)
    
    def _check_extruder(self, ext):
        active_extruder=(self.toohead.get_status()['extruder']==ext)
        if not active_extruder:
            cmd='T{}'.format(ext[-1] if ext[-1].isnumeric() else '0')
            self.gcode.run_script_from_command(cmd)
            self.gcode.respond_info("Activate extruder= "+ext)
            active_extruder=True
        extruder=self.printer.lookup_object(ext)
        can_extruder=extruder.get_status()['can_extrude']
        return (active_extruder and can_extruder)
    
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
            
    def _unload_filament(self, num_retry, ext):
        if (self.loader_sensor_name and 
           not self._check_sensor(self.loader_sensor_name)):
            self.gcode._respond_error('No filament detected!')
            return False
        i = 0
        self.gcode.respond_info("Before while")
        while self._check_sensor(self.toolhead_sensor_name):
            if self._check_extruder(ext):
                self.gcode.run_script_from_command(
                    "G1 E{:.2f} F500".format(self.extrude))
                self.toolhead.wait_moves()
            else:
                self.gcode._respond_error('Prevent Cold Extrusion')
                return False
            if i >= num_retry:
                self.gcode._respond_error("Filament stuck, unable to unload!")
                return False
            i += 1
        
        self._extruder_stepper_move_wait(self.length)
        self.toolhead.wait_moves()
        return True
            
    def cmd_LOAD_FILAMENT(self, gcmd):
        num = gcmd.get_int('RETRY', 3)
        ext = gcmd.get('EXTRUDER')
        if self._load_toolhead(num):
            if self._check_extruder(ext):
                self._load_to_nozzle()
                self.gcode.respond_info('Filament loading succesfull')
            else:
                self.gcode.respond_info(
                    'No cold Extrusion, heat up extruder and finish loading manual')  
                
    def cmd_UNLOAD_FILAMENT(self, gcmd):
        num = gcmd.get_int('RETRY', 3)
        ext = gcmd.get('EXTRUDER')
        if self._unload_filament(num, ext):
            self.gcode.respond_info('Filament unloading succesfull')
               
def load_config_prefix(config):
	return FilamentLoading(config)
