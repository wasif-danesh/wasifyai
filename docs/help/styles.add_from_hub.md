---
action: styles.add_from_hub
screen: images.create
synonyms: [download a style, get a lora, add a lora from hugging face, install a style]
---
# Get a style from Hugging Face

Action: `styles.add_from_hub`

## What it is for

Download a style (a .safetensors LoRA) from a Hugging Face repository to this computer. You are shown the file and
its size and must agree. It is checked when it arrives, then it is in your styles.

## Steps in the app

1. Open **Images › Create**.
2. Under **Styles**, choose **Add a style**, then **From Hugging Face…**.
3. Write the repository's name or paste its address, choose **Look**, choose the file and **Download … and add**.

## Fields

- `repo`: The repository, `owner/name`, or its address.
- `file`: The .safetensors file, when the repository has more than one.

## Limits

- Only .safetensors files; .ckpt and .pt files are never offered (they can run code).
- At most 2 GB.
- One download at a time.
- Asks Hugging Face only once browsing is allowed.

## Needs

- The desktop app and a connection.

## Examples

- Get the anime style Sawata97/flux2_4b_koni_animestyle.

## Problems

- **Browsing is off** Allow it in **Model hub** or from the dialog.
- **This is a model, not a style** The file was deleted again; choose another.
- **Gated** It needs a Hugging Face token in Settings.
