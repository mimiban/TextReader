#!/usr/bin/python
#
# PiTextReader - Raspberry Pi Printed Text-to-Speech Reader
#
# Modifications for Piper TTS using the en_US-amy-medium voice.
#
import RPi.GPIO as GPIO
import os, sys
import logging
import subprocess
import threading
import time

##### USER VARIABLES
DEBUG   = 0 # Debug 0/1 off/on (writes to debug.log)
SPEED   = 1.0   # Speech speed, 0.5 - 2.0 (NOT USED WITH PIPER - see length_scale below)
VOLUME  = 90    # Audio volume
# PIPER SETTINGS (Ensure these paths are correct for your setup)
# This assumes files are in /home/admin/pi/piper/ directory
PIPER_DIR   = "/home/admin/pi/piper/"
PIPER_PATH  = PIPER_DIR + "piper"
MODEL_PATH  = PIPER_DIR + "en_US-amy-medium.onnx"
CONFIG_PATH = PIPER_DIR + "en_US-amy-medium.onnx.json"
# PIPER SPEED CONTROL
# length_scale controls speech speed: lower = faster, higher = slower
# 1.0 = normal, 0.75 = faster, 0.5 = very fast, 1.5 = slower
LENGTH_SCALE = 0.8  # Adjust this to make speech faster/slower
# OTHER SETTINGS
SOUNDS  = "/home/admin/pi/sounds/" # Directory for sound effect(s)
# Optimized camera settings for faster capture
CAMERA  = "rpicam-still -cfx 128:128 --awb auto --rot 180 -t 100 -o /tmp/image.jpg --width 1640 --height 1232"
# GPIO BUTTONS
BTN1    = 24    # The capture button!
BTN2    = 23    # The repeat button! (CHANGE THIS PIN NUMBER TO YOUR WIRING)
LED     = 18    # The button's LED!

### GLOBAL STATE
text_available = False  # Track if there's text to repeat
allow_interrupt = True  # Control when to allow button interrupts

### FUNCTIONS
# Thread controls for background processing
class RaspberryThread(threading.Thread):
    def __init__(self, function):
        self.running = False
        self.function = function
        super(RaspberryThread, self).__init__()
    def start(self):
        self.running = True
        super(RaspberryThread, self).start()
    def run(self):
        while self.running:
            self.function()
    def stop(self):
        self.running = False
# LED ON/OFF
def led(val):
    logger.info('led('+str(val)+')')
    if val:
       GPIO.output(LED,GPIO.HIGH)
    else:
       GPIO.output(LED,GPIO.LOW)
# PLAY SOUND
def sound(val): # Play a sound
    logger.info('sound()')
    time.sleep(0.2)
    cmd = "/usr/bin/aplay -q "+str(val)
    logger.info(cmd)
    os.system(cmd)
    return

# SPEAK STATUS (Updated with correct sample rate and speed control)
def speak(val): # TTS Speak
    logger.info('speak()')
    try:
        # Get sample rate from config - change this to match your model!
        SAMPLE_RATE = '22050'  # Change this after checking the config file
        
        piper_cmd = [PIPER_PATH, '--model', MODEL_PATH, '--config', CONFIG_PATH, 
                     '--length_scale', str(LENGTH_SCALE), '--output_file', '-']
        aplay_cmd = ['aplay', '-q', '-r', SAMPLE_RATE, '-f', 'S16_LE', '-t', 'raw', '-c', '1']
        
        piper_proc = subprocess.Popen(piper_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        aplay_proc = subprocess.Popen(aplay_cmd, stdin=piper_proc.stdout, stderr=subprocess.PIPE)
        
        piper_proc.stdout.close()
        
        piper_proc.stdin.write(val.encode('utf-8'))
        piper_proc.stdin.close()
        
        aplay_proc.wait()
        piper_proc.wait()
        
    except Exception as e:
        logger.error(f"An error occurred during speak: {e}")
    return

# SET VOLUME
def volume(val): # Set Volume for Launch
    logger.info('volume('+str(val)+')')
    vol = int(val)
    cmd = "sudo amixer -q sset PCM,0 "+str(vol)+"%"
    logger.info(cmd)
    os.system(cmd)
    return

# TEXT CLEANUP - Keep $ or convert it properly
def cleanText():
    logger.info('cleanText()')
    
    try:
        with open('/tmp/text.txt', 'r') as f:
            text = f.read()
        
        import re
        
        # Log original text to see what OCR detected
        logger.info(f"Original text: {text[:200]}")
        
        # Remove multiple spaces/newlines
        text = re.sub(r'\s+', ' ', text)
        
        # Fix $ symbol spacing issues
        text = re.sub(r'\$\s+', '$', text)  # "$ 29" -> "$29"
        
        # Fix common OCR mistakes near $ symbol
        text = re.sub(r'\$[Oo]', '$0', text)  # $O -> $0
        text = re.sub(r'\$[lI]', '$1', text)  # $l or $I -> $1
        
        # Fix common OCR number mistakes
        text = re.sub(r'(\d)[Oo](\d)', r'\g<1>0\g<2>', text)
        text = re.sub(r'(\d)[lI](\d)', r'\g<1>1\g<2>', text)
        text = re.sub(r'[Oo](\d)', r'0\g<1>', text)
        text = re.sub(r'(\d)[Oo]', r'\g<1>0', text)
        
        # Fix spacing in times/dates
        text = re.sub(r'(\d)\s*:\s*(\d)', r'\1:\2', text)
        text = re.sub(r'(\d)\s*/\s*(\d)', r'\1/\2', text)
        
        # Convert $ to spoken words AFTER all fixes
        text = re.sub(r'\$(\d+\.?\d*)', r'\1 dollars ', text)  # $29.99 -> 29.99 dollars
        
        # Convert other symbols
        text = text.replace('%', ' percent ')
        text = text.replace('&', ' and ')
        text = text.replace('@', ' at ')
        text = text.replace('#', ' number ')
        text = text.replace('+', ' plus ')
        text = text.replace('=', ' equals ')
        text = text.replace('*', ' times ')
        text = text.replace('°', ' degrees ')
        
        # Clean up multiple spaces
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()
        
        logger.info(f"Cleaned text: {text[:200]}")
        
        with open('/tmp/text.txt', 'w') as f:
            f.write(text)
        
    except Exception as e:
        logger.error(f"Error in cleanText: {e}")
    
    return
        

# Play TTS (Allow Interrupt)
def playTTS():
    logger.info('playTTS()')
    global current_tts
    try:
        # Read and validate text
        with open('/tmp/text.txt', 'r') as f:
            text_content = f.read().strip()
        
        if not text_content:
            logger.error("No text to read!")
            speak("No text detected")
            return
        
        logger.info(f"Reading text: {text_content[:100]}...")
        
        piper_cmd = [PIPER_PATH, '--model', MODEL_PATH, '--config', CONFIG_PATH, 
                     '--length_scale', str(LENGTH_SCALE), '--output_file', '-']
        aplay_cmd = ['aplay', '-q']
        
        current_tts = subprocess.Popen(aplay_cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        piper_proc = subprocess.Popen(piper_cmd, stdin=subprocess.PIPE, stdout=current_tts.stdin, stderr=subprocess.PIPE)
        
        piper_proc.stdin.write(text_content.encode('utf-8'))
        piper_proc.stdin.close()
        
        rt.start()
        
        piper_proc.wait()
        current_tts.stdin.close()
        current_tts.wait()
    except Exception as e:
        logger.error(f"An error occurred during playTTS: {e}")
    return

# Stop TTS (with Interrupt) (kills the aplay process associated with current_tts)
def stopTTS():
    global current_tts, allow_interrupt
    # Only check for interrupts if allowed
    if allow_interrupt and (GPIO.input(BTN1) == GPIO.LOW or GPIO.input(BTN2) == GPIO.LOW):
        logger.info('stopTTS()')
        if current_tts and current_tts.poll() is None:
            current_tts.kill() # This stops the aplay process
        time.sleep(0.5)
    return

# GRAB IMAGE AND CONVERT
def getData():
    logger.info('getData()')
    global text_available
    led(0) # Turn off Button LED
    
    # Take photo (no sound or announcement - faster!)
    cmd = CAMERA
    logger.info(cmd)
    os.system(cmd)
    
    # OCR to text - Optimized for speed
    # --psm 6: Assume uniform block of text (faster)
    # --oem 3: Use both legacy and LSTM engines (best balance)
    # -c tessedit_do_invert=0: Skip inversion check (faster)
    cmd = "/usr/bin/tesseract /tmp/image.jpg /tmp/text --psm 6 --oem 3 -c tessedit_do_invert=0"
    logger.info(cmd)
    os.system(cmd)
    
    # Cleanup text
    cleanText()
    
    # Mark that text is now available
    text_available = True
    
    # Start reading text immediately
    playTTS()
    return

# REPEAT LAST TEXT
def repeatText():
    logger.info('repeatText()')
    # Simply play the existing text file
    playTTS()
    return

######
# MAIN
######
try:
    global rt
    # Setup Logging
    logger = logging.getLogger()
    handler = logging.FileHandler('debug.log')
    if DEBUG:
        logger.setLevel(logging.INFO)
        handler.setLevel(logging.INFO)
    else:
        logger.setLevel(logging.ERROR)
        handler.setLevel(logging.ERROR)
    log_format = '%(asctime)-6s: %(name)s - %(levelname)s - %(message)s'
    handler.setFormatter(logging.Formatter(log_format))
    logger.addHandler(handler)
    logger.info('Starting')

    # Setup GPIO buttons
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings (False)

    GPIO.setup(BTN1, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(BTN2, GPIO.IN, pull_up_down=GPIO.PUD_UP)  # NEW: Setup repeat button
    GPIO.setup(LED, GPIO.OUT)

    # Threaded audio player
    rt = RaspberryThread( function = stopTTS ) # Stop Speaking text
    # Initialize current_tts variable
    current_tts = None
    volume(VOLUME)
    speak("OK, ready")
    led(1)
    while True:
        if GPIO.input(BTN1) == GPIO.LOW:
            # Btn 1 - Capture and read
            allow_interrupt = True  # Enable interrupts
            getData()
            rt.stop()
            rt = RaspberryThread( function = stopTTS ) # Stop Speaking text
            led(1)
            time.sleep(0.5)
            speak("OK, ready")
            
        elif GPIO.input(BTN2) == GPIO.LOW:
            # Btn 2 - Repeat last text
            logger.info('Button 2 pressed - Repeat')
            if text_available:
                led(0)
                allow_interrupt = False  # Temporarily disable interrupt checking
                time.sleep(0.3)  # Wait for button release
                allow_interrupt = True  # Re-enable interrupts
                repeatText()
                rt.stop()
                rt = RaspberryThread( function = stopTTS )
                led(1)
                time.sleep(0.5)
                speak("OK, ready")
            else:
                speak("No text available. Please capture an image first.")
                time.sleep(0.5)
            
        time.sleep(0.2)
except KeyboardInterrupt:
    logger.info("exiting")
GPIO.cleanup() #Reset GPIOs
sys.exit(0)
