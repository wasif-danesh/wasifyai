---
action: model3d.generate
screen: model3d
synonyms: [3d model, make a 3d model, 3d object, glb, 3d from a picture, image to 3d, text to 3d, turn a picture into 3d, model of my mascot, 3d print, turntable]
---
# Make a 3D model

Action: `model3d.generate`

## What it is for

Turn a picture of one object into a textured 3D model you can turn around on the screen and save as a
GLB file. You can start from a picture of your own, or describe the object in words: the app makes four
pictures of it, you pick one, and only then does the long step start. Everything is made on this
computer and nothing is sent anywhere. 3D models are experimental.

## Steps in the app

1. Open **3D model** The first time, choose
   Download and set up: it shows the size (about 9 GB) before it starts.
2. Choose a picture, or choose Words, describe the object and choose Make 4 pictures, then Use this
   picture on the one you like.
3. Look at the cut-out ("is this the object?") and what the app found: one object, all of it in the
   picture, in the middle. Warnings do not stop you; a picture with no object does.
4. Choose Light, Standard or Detailed, say that you may use the picture, and choose Make the 3D model.
5. It takes about 5 to 25 minutes. You can leave the screen; the model will be in Your 3D models. Drag
   to turn it, scroll to zoom, choose Save a copy (GLB) to keep the file.

## Fields

- `image_id`: The picture of the library to make a model of.
- `title`: A name for the model.
- `prompt`: The words the picture was made from, so the model can be found by them.
- `detail`: light, standard or detailed (the size of the texture: 1024, 2048 or 4096 pixels).
- `seed`: The same seed gives the same model. Make it again uses it.

## Limits

- One model at a time. Choose Cancel to stop one that is running; nothing is kept.
- About 19 GB of memory is held while it works, so a Mac with 16 GB cannot make one, and other big
  models (the chat model, the image model) are put away first.
- The model has about a million triangles and is not watertight, so it suits viewing and rendering
  better than 3D printing. A straight-on picture at eye level on a plain background works best; glass,
  mirrors, thin parts, fur and several objects do not come out well.
- Pictures of real people need their agreement: you are asked to confirm it.
- Built with DINOv3: the picture encoder is under Meta's DINOv3 licence, which is shown on the setup card
  and the screen.

## Needs

- 3D set up (a download of about 9 GB, shown before it starts), about 9 GB of free disk space, and about
  19 GB of free memory. Only Apple-silicon Macs for now. To start from words, the image model too.

## Examples

- Make a 3D model of the picture of my mascot.
- Turn the picture of a ceramic frog mug into a 3D model, detailed.

## Problems

- **No object was found in this picture** Use a picture of one object on a plain background.
- **A 3D model is already being made** Wait for it to finish or cancel it.
- **Not enough memory** Close other apps, or use a Mac with more memory.
- **The 3D component is not set up** Open **3D model** and choose Download and set up.
