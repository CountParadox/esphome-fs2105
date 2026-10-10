"""Compile the production C++ driver against a fake I2C bus. Requires g++."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
STUB = r'''
#pragma once
#include <cstdint>
#include <cstddef>
#include <functional>
#include <string>
#include <map>
#include <vector>
namespace esphome {
namespace setup_priority { constexpr float DATA=600; }
class PollingComponent { public:
 virtual ~PollingComponent()=default;
 virtual void setup(){} virtual void update(){} virtual void dump_config(){}
 virtual float get_setup_priority() const{return 0;}
 void set_timeout(const char*, uint32_t, std::function<void()> f){ f(); }
 void status_set_warning(){} void status_clear_warning(){}
};
namespace number { class Number {public: float state=0; void publish_state(float v){state=v;} protected: virtual void control(float)=0;}; }
namespace switch_ { class Switch {public: bool state=false; void publish_state(bool v){state=v;} protected: virtual void write_state(bool)=0;}; }
namespace sensor { class Sensor {public: float state=0; void publish_state(float v){state=v;}}; }
namespace binary_sensor { class BinarySensor {public: bool state=false; void publish_state(bool v){state=v;}}; }
namespace text_sensor { class TextSensor {public: std::string state; void publish_state(const char *v){state=v;}}; }
namespace i2c {
enum ErrorCode {ERROR_OK=0, ERROR_UNKNOWN=1};
class I2CDevice {public:
 std::map<uint8_t,uint16_t> regs;
 std::vector<uint8_t> writes;
 bool fail_reads=false; int fail_write=-1; bool corrupt=false;
 ErrorCode read_register(uint8_t r,uint8_t *b,size_t){
  if(fail_reads)return ERROR_UNKNOWN;
  b[0]=regs[r]>>8; b[1]=regs[r];return ERROR_OK;
 }
 ErrorCode write_register(uint8_t r,const uint8_t *b,size_t){
  writes.push_back(r); if(r==fail_write)return ERROR_UNKNOWN;
  regs[r]=(uint16_t(b[0])<<8)|b[1]; if(corrupt)regs[r]^=0x80;
  return ERROR_OK;
 }
 protected: uint8_t address_=0x68;
}; }
}
#define ESP_LOGCONFIG(...) ((void)0)
#define ESP_LOGW(...) ((void)0)
#define LOG_I2C_DEVICE(...) ((void)0)
'''
TEST = r'''
#include "fs2105.h"
#include <cassert>
#include <cmath>
using namespace esphome;
using namespace esphome::fs2105;
void seed(FS2105 &a) {
 a.regs={{3,0x2019},{0x30,0x9555},{0x39,0xAB55},{0x3A,0xCD2A},{0x3B,0xEF7F}};
}
int main() {
 // Read-only boot and all controls must not write.
 FS2105 ro; seed(ro); ro.setup(); assert(ro.is_connected());
 assert(ro.writes.empty()); assert(!ro.set_volume_db(-30));
 assert(!ro.toggle_mute()); assert(ro.writes.empty());
 // Wrong ID is never accepted and no startup writes occur.
 FS2105 wrong; seed(wrong); wrong.set_enable_control(true);
 wrong.regs[3]=0x9999; wrong.setup(); assert(!wrong.is_connected());
 assert(wrong.writes.empty());
 // Startup sets all levels, keeps low seven bits, unmutes, preserves other DAC bits.
 FS2105 a; seed(a); a.set_enable_control(true); a.setup();
 assert(a.is_ready()); assert(!a.is_muted());
 assert((a.regs[0x39]&127)==0x55 && (a.regs[0x3A]&127)==0x2A && (a.regs[0x3B]&127)==0x7F);
 assert((a.regs[0x39]>>7)==298); // -39.9375 dB
 assert((a.regs[0x30]&~0x3330)==(0x9555&~0x3330));
 auto writes=a.writes.size(); a.update(); assert(a.writes.size()==writes);
 assert(a.set_mute(true)); assert(a.is_muted());
 assert(a.change_volume(0.9375f)); assert(a.is_muted());
 assert((a.regs[0x39]>>7)==303);
 assert(a.toggle_mute()); assert(!a.is_muted());
 assert(a.set_volume_db(100)); assert((a.regs[0x39]>>7)==511);
 assert(a.set_volume_db(-100)); assert((a.regs[0x39]>>7)==85);
 // External changes are read back; polling never forces our previous value.
 VolumeNumber n; sensor::Sensor right; binary_sensor::BinarySensor diff;
 a.set_volume_number(&n); a.set_channel_sensor(1,&right); a.set_channels_differ(&diff);
 a.regs[0x39]=(400<<7)|0x55; a.update(); assert(diff.state);
 assert(n.state==(400-511)*0.1875f);
 assert(a.change_volume(0.9375f)); assert((a.regs[0x39]>>7)==405);
 // Partial write failure latches off; reconnection/polling never retries it.
 a.fail_write=0x3A; assert(!a.set_volume_db(-20)); assert(a.has_write_fault());
 writes=a.writes.size(); a.fail_write=-1; a.update();
 assert(a.is_connected()); assert(!a.set_mute(true)); assert(a.writes.size()==writes);
 a.clear_write_fault(); assert(a.writes.size()==writes); assert(a.set_mute(true));
 // Readback mismatch detected, no false successful command.
 a.corrupt=true; assert(!a.set_volume_db(-30)); assert(a.has_write_fault());
 // Missing amp recovers, but commands are never queued during outage.
 FS2105 b; seed(b); b.set_enable_control(true); b.set_apply_startup(false);
 b.fail_reads=true; b.setup(); assert(!b.set_volume_db(-30)); assert(b.writes.empty());
 b.fail_reads=false; b.update(); assert(b.writes.empty()); assert(b.is_ready());
 b.fail_reads=true; b.update(); assert(!b.is_connected());
 b.fail_reads=false; b.update(); assert(b.writes.empty());
}
'''
with tempfile.TemporaryDirectory() as temp:
    p = Path(temp)
    (p/'stub.h').write_text(STUB)
    for header in ('core/component.h', 'core/log.h', 'components/i2c/i2c.h',
                   'components/number/number.h', 'components/switch/switch.h',
                   'components/sensor/sensor.h', 'components/binary_sensor/binary_sensor.h',
                   'components/text_sensor/text_sensor.h'):
        f = p/'esphome'/header
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text('#include "stub.h"\n')
    (p/'test.cpp').write_text(TEST)
    component = ROOT/'components/fs2105'
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Wno-unused-variable',
                    '-I'+str(p),'-I'+str(component),str(component/'fs2105.cpp'),
                    str(p/'test.cpp'),'-o',str(p/'test')],check=True)
    subprocess.run([str(p/'test')], check=True)
print('PASS: read-only mode, ID, startup, masks, clamping, mute, feedback, failures and recovery')
