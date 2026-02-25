###
# View with:
# ffplay -fflags nobuffer -flags low_delay -framedrop -analyzeduration 0 -probesize 32 \
# "udp://127.0.0.1:1234?fifo_size=1000000&overrun_nonfatal=1"
###
import bpy
import subprocess
import time
import numpy as np
import atexit
import shutil

IMAGE_NAME = "PaintTexture"
STREAM_FPS = 15
UDP_URL = "udp://127.0.0.1:1234?pkt_size=1316"
FFMPEG_BIN = "ffmpeg"   # set to "/usr/bin/ffmpeg" if needed

# While running, send at least one keyframe periodically so viewers can join even if you are not painting.
KEEPALIVE_SECONDS = 1.0


class TextureStreamer:
    def __init__(self):
        self.proc = None
        self.running = False
        self.last_error = ""

        self.last_send_time = 0.0
        self.frames_sent = 0

    def _set_error(self, msg: str):
        self.last_error = msg
        print("[TextureStreamer]", msg)

    def start(self):
        if self.running:
            return

        self.last_error = ""
        self.frames_sent = 0
        self.last_send_time = 0.0

        img = bpy.data.images.get(IMAGE_NAME)
        if img is None:
            self._set_error(f"Image not found: {IMAGE_NAME}")
            return

        W, H = img.size
        if W == 0 or H == 0:
            self._set_error(f"Invalid image size: {W}x{H}")
            return

        if FFMPEG_BIN == "ffmpeg" and shutil.which("ffmpeg") is None:
            self._set_error("ffmpeg not found in PATH. Set FFMPEG_BIN to an absolute path, e.g. /usr/bin/ffmpeg")
            return

        ffmpeg_cmd = [
            FFMPEG_BIN,
            "-loglevel", "warning",
            "-f", "rawvideo",
            "-pix_fmt", "rgba",
            "-s", f"{W}x{H}",
            "-r", str(STREAM_FPS),
            "-i", "-",
            "-an",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-tune", "zerolatency",
            "-pix_fmt", "yuv420p",
            "-g", str(STREAM_FPS),
            "-keyint_min", str(STREAM_FPS),
            "-sc_threshold", "0",
            "-f", "mpegts",
            "-mpegts_flags", "+resend_headers",
            UDP_URL
        ]

        try:
            self.proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE)
        except Exception as e:
            self.proc = None
            self._set_error(f"Failed to start ffmpeg: {e}")
            return

        self.running = True
        bpy.app.timers.register(self.stream, persistent=True)
        print("Streaming started")

    def stop(self):
        if not self.running:
            return

        self.running = False

        if self.proc:
            try:
                if self.proc.stdin:
                    self.proc.stdin.close()
            except Exception:
                pass
            try:
                self.proc.terminate()
            except Exception:
                pass
            self.proc = None

        print("Streaming stopped")

    def stream(self):
        if not self.running:
            return None

        if self.proc and (self.proc.poll() is not None):
            self._set_error("ffmpeg exited unexpectedly.")
            self.stop()
            return None

        img = bpy.data.images.get(IMAGE_NAME)
        if img is None:
            self._set_error(f"Image missing: {IMAGE_NAME}")
            self.stop()
            return None

        now = time.time()
        period = 1.0 / STREAM_FPS

        # Send a frame if:
        # - you painted (img.is_dirty), OR
        # - we have not sent anything for KEEPALIVE_SECONDS (helps ffplay join)
        should_send = bool(img.is_dirty) or (now - self.last_send_time) > KEEPALIVE_SECONDS
        if not should_send:
            return period

        px = np.asarray(img.pixels, dtype=np.float32)
        u8 = (px * 255.0).clip(0, 255).astype(np.uint8)

        try:
            if not self.proc or not self.proc.stdin:
                self._set_error("ffmpeg process not available.")
                self.stop()
                return None
            self.proc.stdin.write(u8.tobytes())
            self.last_send_time = now
            self.frames_sent += 1
        except Exception as e:
            self._set_error(f"Write failed: {e}")
            self.stop()
            return None

        return period

    def status_text(self) -> str:
        if self.last_error:
            return "Error"
        return "Streaming" if self.running else "Stopped"


streamer = TextureStreamer()
atexit.register(streamer.stop)


class STREAM_OT_start(bpy.types.Operator):
    bl_idname = "stream.start"
    bl_label = "Start Texture Stream"

    def execute(self, context):
        streamer.start()
        return {'FINISHED'}


class STREAM_OT_stop(bpy.types.Operator):
    bl_idname = "stream.stop"
    bl_label = "Stop Texture Stream"

    def execute(self, context):
        streamer.stop()
        return {'FINISHED'}


class STREAM_PT_panel(bpy.types.Panel):
    bl_label = "UV Texture Stream"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Stream"

    def draw(self, context):
        layout = self.layout

        img = bpy.data.images.get(IMAGE_NAME)
        size_str = "n/a"
        if img is not None:
            size_str = f"{img.size[0]} x {img.size[1]}"

        box = layout.box()
        row = box.row()
        row.label(text="Status:")
        row.label(text=streamer.status_text())

        box.label(text=f"Image: {IMAGE_NAME}")
        box.label(text=f"Size: {size_str}")
        box.label(text=f"FPS: {STREAM_FPS}")
        box.label(text=f"Output: {UDP_URL}")

        # This is the key "is it actually generating packets?" indicator:
        box.label(text=f"Frames sent: {streamer.frames_sent}")
        if streamer.last_send_time > 0:
            ago = time.time() - streamer.last_send_time
            box.label(text=f"Last send: {ago:.2f}s ago")

        if streamer.last_error:
            err = layout.box()
            err.label(text="Last error:")
            err.label(text=str(streamer.last_error)[:120])

        row = layout.row()
        row.enabled = not streamer.running
        row.operator("stream.start", text="Start")

        row = layout.row()
        row.enabled = streamer.running
        row.operator("stream.stop", text="Stop")


def register():
    bpy.utils.register_class(STREAM_OT_start)
    bpy.utils.register_class(STREAM_OT_stop)
    bpy.utils.register_class(STREAM_PT_panel)

def unregister():
    bpy.utils.unregister_class(STREAM_PT_panel)
    bpy.utils.unregister_class(STREAM_OT_stop)
    bpy.utils.unregister_class(STREAM_OT_start)

if __name__ == "__main__":
    register()