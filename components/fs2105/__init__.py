"""FS2105SE control-only I2C interface. No audio streaming or chip reset."""
import math
import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import i2c, number, switch, sensor, binary_sensor, text_sensor
from esphome.const import CONF_ID

DEPENDENCIES = ["i2c"]
AUTO_LOAD = ["number", "switch", "sensor", "binary_sensor", "text_sensor"]
ns = cg.esphome_ns.namespace("fs2105")
FS2105 = ns.class_("FS2105", cg.PollingComponent, i2c.I2CDevice)
VolumeNumber = ns.class_("VolumeNumber", number.Number)
MuteSwitch = ns.class_("MuteSwitch", switch.Switch)


def validate(config):
    if not config["min_volume"] <= config["startup_volume"] <= config["max_volume"]:
        raise cv.Invalid("Require min_volume <= startup_volume <= max_volume")
    if math.ceil(511 + config["min_volume"] / 0.1875) > math.floor(511 + config["max_volume"] / 0.1875):
        raise cv.Invalid("Volume range must include at least one hardware step (0.1875 dB)")
    if config["address"] not in range(0x68, 0x6C):
        raise cv.Invalid("FS2105SE documented 7-bit addresses are 0x68 through 0x6B")
    return config

CONFIG_SCHEMA = cv.All(cv.Schema({
    cv.GenerateID(): cv.declare_id(FS2105),
    cv.Optional("enable_control", default=False): cv.boolean,
    cv.Optional("apply_startup", default=True): cv.boolean,
    cv.Optional("startup_volume", default=-40.0): cv.float_range(min=-95.8125, max=0),
    cv.Optional("min_volume", default=-80.0): cv.float_range(min=-95.8125, max=0),
    cv.Optional("max_volume", default=0.0): cv.float_range(min=-95.8125, max=0),
    cv.Optional("boot_delay", default="10s"): cv.positive_time_period_milliseconds,
    cv.Optional("volume"): number.number_schema(VolumeNumber, unit_of_measurement="dB"),
    cv.Optional("mute"): switch.switch_schema(MuteSwitch),
    cv.Optional("left_volume"): sensor.sensor_schema(unit_of_measurement="dB", accuracy_decimals=3),
    cv.Optional("right_volume"): sensor.sensor_schema(unit_of_measurement="dB", accuracy_decimals=3),
    cv.Optional("woofer_volume"): sensor.sensor_schema(unit_of_measurement="dB", accuracy_decimals=3),
    cv.Optional("connected"): binary_sensor.binary_sensor_schema(device_class="connectivity"),
    cv.Optional("channels_differ"): binary_sensor.binary_sensor_schema(),
    cv.Optional("status"): text_sensor.text_sensor_schema(),
}).extend(cv.polling_component_schema("5s")).extend(i2c.i2c_device_schema(0x68)), validate)

async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)
    await i2c.register_i2c_device(var, config)
    for key in ("enable_control", "apply_startup", "startup_volume", "min_volume", "max_volume"):
        cg.add(getattr(var, "set_" + key)(config[key]))
    cg.add(var.set_boot_delay(config["boot_delay"].total_milliseconds))
    if "volume" in config:
        obj = await number.new_number(config["volume"], min_value=(math.ceil(511 + config["min_volume"] / 0.1875) - 511) * 0.1875,
                                      max_value=(math.floor(511 + config["max_volume"] / 0.1875) - 511) * 0.1875, step=0.1875)
        cg.add(obj.set_parent(var))
        cg.add(var.set_volume_number(obj))
    if "mute" in config:
        obj = await switch.new_switch(config["mute"])
        cg.add(obj.set_parent(var))
        cg.add(var.set_mute_switch(obj))
    for index, key in enumerate(("left_volume", "right_volume", "woofer_volume")):
        if key in config:
            obj = await sensor.new_sensor(config[key])
            cg.add(var.set_channel_sensor(index, obj))
    for key in ("connected", "channels_differ"):
        if key in config:
            obj = await binary_sensor.new_binary_sensor(config[key])
            cg.add(getattr(var, "set_" + key)(obj))
    if "status" in config:
        cg.add(var.set_status(await text_sensor.new_text_sensor(config["status"])))
