# blender-uv-texture-stream


On a terminal, run: 

```
ffplay \
  -fflags nobuffer \
  -flags low_delay \
  -framedrop \
  -analyzeduration 0 \
  -probesize 32 \
  "udp://127.0.0.1:1234?fifo_size=1000000&overrun_nonfatal=1
```



