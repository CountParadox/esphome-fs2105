#pragma once
#include "esphome/core/component.h"
#include "esphome/components/i2c/i2c.h"
#include "esphome/components/number/number.h"
#include "esphome/components/switch/switch.h"
#include "esphome/components/sensor/sensor.h"
#include "esphome/components/binary_sensor/binary_sensor.h"
#include "esphome/components/text_sensor/text_sensor.h"

namespace esphome { namespace fs2105 {
class FS2105;
class VolumeNumber : public number::Number {
 public:
  void set_parent(FS2105 *parent) { parent_ = parent; }
 protected:
  void control(float value) override;
  FS2105 *parent_{};
};
class MuteSwitch : public switch_::Switch {
 public:
  void set_parent(FS2105 *parent) { parent_ = parent; }
 protected:
  void write_state(bool value) override;
  FS2105 *parent_{};
};

class FS2105 : public PollingComponent, public i2c::I2CDevice {
 public:
  void setup() override;
  void update() override;
  void dump_config() override;
  float get_setup_priority() const override { return setup_priority::DATA; }
  void set_enable_control(bool v) { enable_control_ = v; }
  void set_apply_startup(bool v) { apply_startup_ = v; }
  void set_startup_volume(float v) { startup_volume_ = v; }
  void set_min_volume(float v) { min_volume_ = v; }
  void set_max_volume(float v) { max_volume_ = v; }
  void set_boot_delay(uint32_t v) { boot_delay_ = v; }
  void set_volume_number(VolumeNumber *v) { volume_ = v; }
  void set_mute_switch(MuteSwitch *v) { mute_ = v; }
  void set_channel_sensor(uint8_t i, sensor::Sensor *v) { channel_[i] = v; }
  void set_connected(binary_sensor::BinarySensor *v) { connected_ = v; }
  void set_channels_differ(binary_sensor::BinarySensor *v) { differ_ = v; }
  void set_status(text_sensor::TextSensor *v) { status_ = v; }
  bool set_volume_db(float db);
  bool change_volume(float delta_db);
  bool set_mute(bool muted);
  bool toggle_mute();
  void refresh() { update(); }
  bool is_connected() const { return online_; }
  bool is_ready() const { return initialized_ && online_ && !write_fault_; }
  bool is_muted() const { return (dac_ & 0x1110) == 0x1110; }
  bool has_write_fault() const { return write_fault_; }
  // Explicit user action after inspecting a write failure; no queued commands replayed.
  void clear_write_fault();
 protected:
  bool read_reg_(uint8_t reg, uint16_t &value);
  bool update_reg_(uint8_t reg, uint16_t mask, uint16_t value);
  bool snapshot_();
  void publish_();
  void fault_(const char *reason);
  bool prepare_write_();
  bool write_volume_(float db);
  void set_status_(const char *value);
  static float to_db_(uint16_t value) { return (int(value >> 7) - 511) * 0.1875f; }
  bool enable_control_{false}, apply_startup_{true}, initialized_{false};
  bool boot_ready_{false}, online_{false}, write_fault_{false};
  float startup_volume_{-40}, min_volume_{-80}, max_volume_{0};
  uint32_t boot_delay_{10000};
  uint16_t values_[3]{}, dac_{};
  VolumeNumber *volume_{};
  MuteSwitch *mute_{};
  sensor::Sensor *channel_[3]{};
  binary_sensor::BinarySensor *connected_{}, *differ_{};
  text_sensor::TextSensor *status_{};
};
}}  // namespace esphome::fs2105
