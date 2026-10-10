#include "fs2105.h"
#include "esphome/core/log.h"
#include <cmath>
#include <algorithm>

namespace esphome { namespace fs2105 {
static const char *const TAG = "fs2105";
static constexpr uint8_t VOLUME_REGS[] = {0x39, 0x3A, 0x3B};
void VolumeNumber::control(float value) { parent_->set_volume_db(value); }
void MuteSwitch::write_state(bool value) { parent_->set_mute(value); }

void FS2105::set_status_(const char *value) {
  if (status_ != nullptr && status_->state != value) status_->publish_state(value);
}
void FS2105::setup() {
  if (connected_) connected_->publish_state(false);
  set_status_("Waiting for amplifier boot");
  set_timeout("boot", boot_delay_, [this]() { boot_ready_ = true; update(); });
}
void FS2105::dump_config() {
  ESP_LOGCONFIG(TAG, "FS2105SE control-only driver (hardware validation required)");
  LOG_I2C_DEVICE(this);
  ESP_LOGCONFIG(TAG, "Writes: %s; startup: %s; range %.3f..%.3f dB",
                enable_control_ ? "enabled" : "disabled",
                apply_startup_ ? "set volume and UNMUTE" : "preserve", min_volume_, max_volume_);
}
void FS2105::fault_(const char *reason) {
  online_ = false;
  status_set_warning();
  if (connected_) connected_->publish_state(false);
  if (volume_) volume_->publish_state(NAN);
  for (auto *s : channel_) if (s) s->publish_state(NAN);
  // Boolean entities retain their last sample; connected=false makes it invalid.
  set_status_(reason);
  ESP_LOGW(TAG, "%s", reason);
}
bool FS2105::read_reg_(uint8_t reg, uint16_t &value) {
  uint8_t bytes[2];
  if (read_register(reg, bytes, 2) != i2c::ERROR_OK) {
    ESP_LOGW(TAG, "Read failed: addr=0x%02X reg=0x%02X", address_, reg);
    return false;
  }
  value = (uint16_t(bytes[0]) << 8) | bytes[1];
  return true;
}
bool FS2105::update_reg_(uint8_t reg, uint16_t mask, uint16_t value) {
  uint16_t old, verified;
  if (!read_reg_(reg, old)) {
    write_fault_ = true; fault_("Read before write failed; writes latched off"); return false;
  }
  uint16_t next = (old & ~mask) | (value & mask);
  if (next != old) {
    const uint8_t bytes[] = {uint8_t(next >> 8), uint8_t(next)};
    if (write_register(reg, bytes, 2) != i2c::ERROR_OK) {
      write_fault_ = true; fault_("Write failed; writes latched off"); return false;
    }
  }
  if (!read_reg_(reg, verified) || (verified & mask) != (next & mask)) {
    write_fault_ = true; fault_("Readback mismatch; writes latched off"); return false;
  }
  return true;
}
bool FS2105::snapshot_() {
  uint16_t ident, volumes[3], dac;
  if (!read_reg_(0x03, ident)) { fault_("No chip response"); return false; }
  if (ident != 0x2019) {
    ESP_LOGW(TAG, "Unexpected DEVID=0x%04X (expected 0x2019)", ident);
    fault_("Unexpected chip ID; no writes"); return false;
  }
  if (!read_reg_(0x30, dac)) { fault_("Mute read failed"); return false; }
  for (uint8_t i = 0; i < 3; i++) {
    if (!read_reg_(VOLUME_REGS[i], volumes[i])) { fault_("Volume read failed"); return false; }
  }
  for (uint8_t i = 0; i < 3; i++) values_[i] = volumes[i];
  dac_ = dac;
  online_ = true;
  if (connected_) connected_->publish_state(true);
  if (!write_fault_) status_clear_warning();
  return true;
}
void FS2105::publish_() {
  for (uint8_t i = 0; i < 3; i++) if (channel_[i]) channel_[i]->publish_state(to_db_(values_[i]));
  // Master's displayed feedback is LEFT. Separate sensors expose all three.
  if (volume_) volume_->publish_state(to_db_(values_[0]));
  if (mute_) mute_->publish_state(is_muted());
  bool unequal = (values_[0] >> 7) != (values_[1] >> 7) ||
                 (values_[0] >> 7) != (values_[2] >> 7);
  bool partial_mute = (dac_ & 0x1110) != 0 && !is_muted();
  if (differ_) differ_->publish_state(unequal || partial_mute);
  set_status_(write_fault_ ? "Write fault latched; inspect then clear" :
              !enable_control_ ? "Read-only diagnostics" :
              unequal || partial_mute ? "Channel levels or mute states differ" : "Ready");
}
void FS2105::update() {
  if (!boot_ready_ || !snapshot_()) return;
  if (!initialized_) {
    // Only try startup ONCE, even if a write fails part-way through.
    initialized_ = true;
    if (enable_control_ && apply_startup_) {
      if (!write_volume_(startup_volume_) ||
          !update_reg_(0x30, 0x2220, 0x2220) ||
          !update_reg_(0x30, 0x1110, 0)) return;
      if (!snapshot_()) { write_fault_ = true; return; }
    }
  }
  publish_();
}
bool FS2105::prepare_write_() {
  if (!enable_control_ || !boot_ready_ || !initialized_ || write_fault_) {
    ESP_LOGW(TAG, "Command rejected: diagnostics, boot wait, or latched write fault");
    return false;
  }
  return snapshot_();  // Fresh ID and values before every command, no stale stepping.
}
bool FS2105::write_volume_(float db) {
  if (!std::isfinite(db)) return false;
  const int lower = int(std::ceil(511.0f + min_volume_ / 0.1875f));
  const int upper = int(std::floor(511.0f + max_volume_ / 0.1875f));
  int code = int(std::lround(511.0f + std::max(min_volume_, std::min(max_volume_, db)) / 0.1875f));
  code = std::max(lower, std::min(upper, code));
  for (auto reg : VOLUME_REGS) if (!update_reg_(reg, 0xFF80, uint16_t(code << 7))) return false;
  return true;
}
bool FS2105::set_volume_db(float db) {
  if (!std::isfinite(db) || !prepare_write_()) return false;
  if (!write_volume_(db)) return false;
  if (!snapshot_()) { write_fault_ = true; return false; }
  publish_(); return true;
}
bool FS2105::change_volume(float delta_db) {
  if (!std::isfinite(delta_db) || !prepare_write_()) return false;
  if (!write_volume_(to_db_(values_[0]) + delta_db)) return false;
  if (!snapshot_()) { write_fault_ = true; return false; }
  publish_(); return true;
}
bool FS2105::set_mute(bool muted) {
  if (!prepare_write_() || !update_reg_(0x30, 0x1110, muted ? 0x1110 : 0)) return false;
  if (!snapshot_()) { write_fault_ = true; return false; }
  publish_(); return true;
}
bool FS2105::toggle_mute() {
  if (!prepare_write_()) return false;
  // A partial mute becomes ALL muted on the first press.
  if (!update_reg_(0x30, 0x1110, is_muted() ? 0 : 0x1110)) return false;
  if (!snapshot_()) { write_fault_ = true; return false; }
  publish_(); return true;
}
void FS2105::clear_write_fault() {
  if (!boot_ready_ || !snapshot_()) return;
  write_fault_ = false;
  status_clear_warning();
  publish_(); // Never reapply startup or replay an earlier failed command.
}
}}  // namespace esphome::fs2105
