This folder is bundled into the SPIFFS partition labeled "model".

Put ESP-SR runtime models here (copied before build), for example:
- Noise suppression: nsnet2 model file(s) (filenames containing "nsnet2")
- Optional VAD model: VADNET (filenames containing "vadnet")

Build notes:
- CMake packs this folder via `spiffs_create_partition_image(model ...)` into the partition defined in `partitions/v1/16m.csv`.
- Ensure total size fits the model partition (default ~960KB). If models are larger, increase the `model` partition size and adjust app offsets accordingly.

Usage in firmware:
- The AFE audio processor scans the "model" partition using `esp_srmodel_init("model")` and `esp_srmodel_filter(...)`.
- If an nsnet2 model is found, NS will be enabled automatically (AFE_NS_MODE_NET).
- If no NS model is present, the AFE will run without noise suppression.

How to get models:
- Obtain ESP-SR models from Espressif resources (e.g., ESP-SR releases or IDF examples). Place the binary/model files here so their names include `nsnet2` (for NS) and optionally `vadnet`.
