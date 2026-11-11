import sys, runpy
sys.argv[0] = 'esptool'
import esp_patch
runpy.run_module('esptool', run_name='__main__')
