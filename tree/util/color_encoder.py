from adafruit_seesaw import seesaw, rotaryio, digitalio, neopixel

class ColorEncoder:
    def __init__(self, i2c, address, color, amount = 16):
        self.color = color
        self.amount = amount
        self.last_position = 0

        ss = seesaw.Seesaw(i2c, address)
        ss.pin_mode(24, ss.INPUT_PULLUP)

        self.encoder = rotaryio.IncrementalEncoder(ss)
        self.switch = digitalio.DigitalIO(ss, 24)
        self.pixel = neopixel.NeoPixel(ss, 6, 1)

        self.updateColor()


    def update(self):
        global encoder_steps

        position = -self.encoder.position
        if position == self.last_position: return

        if position > self.last_position: self.amount += 1
        else: self.amount -= 1

        if self.amount > encoder_steps: self.amount = encoder_steps
        if self.amount < 0: self.amount = 0

        self.last_position = position
        self.updateColor();

    def updateColor(self):
        c = [0,0,0]
        c[self.color] = self.amount
        self.pixel.fill(c)

    def isPressed(self):
        return not self.switch.value


    @property
    def brightness(self):
        self.pixel.brightness

    @brightness.setter
    def brightness(self, brightness):
        self.pixel.brightness = brightness