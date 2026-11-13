# fal.ai model inputs for v1 (FA0, read 2026-11-12)

Generated from fal.ai's OpenAPI for each chosen endpoint (`https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=…`).
`*` marks a required field; `=` its default; enums are cut to eight values. Spike note: `fal-v1-fa0.md`.

## `openai/gpt-image-2.5/sunburst/text-to-image`

Returns: images

- `output_format`: string ['jpeg', 'png', 'webp'] =png
- `num_images`: integer =1
- `output_compression`: integer/null
- `image_size`: ImageSize/string ['square_hd', 'square', 'portrait_4_3', 'portrait_16_9', 'landscape_4_3', 'landscape_16_9', 'auto'] =landscape_4_3
- `quality`: string ['auto', 'low', 'medium', 'high', 'xhigh', 'max'] =high
- `background`: string ['auto', 'transparent', 'opaque'] =auto
- `prompt`: *string
- `sync_mode`: boolean =False
- `enable_safety_checker`: boolean =True

## `openai/gpt-image-2.5/sunburst/edit`

Returns: images

- `output_format`: string ['jpeg', 'png', 'webp'] =png
- `num_images`: integer =1
- `image_urls`: *array
- `mask_url`: string/null
- `image_size`: ImageSize/string ['square_hd', 'square', 'portrait_4_3', 'portrait_16_9', 'landscape_4_3', 'landscape_16_9', 'auto'] =auto
- `output_compression`: integer/null
- `quality`: string ['auto', 'low', 'medium', 'high', 'xhigh', 'max'] =high
- `background`: string ['auto', 'transparent', 'opaque'] =auto
- `prompt`: *string
- `sync_mode`: boolean =False
- `enable_safety_checker`: boolean =True

## `google/nano-banana-2.1`

Returns: images, description

- `limit_generations`: boolean =True
- `enable_web_search`: boolean =False
- `prompt`: *string
- `aspect_ratio`: string/null ['auto', '21:9', '16:9', '3:2', '4:3', '5:4', '1:1', '4:5'] =auto
- `resolution`: string ['1K', '2K', '4K'] =1K
- `seed`: integer/null
- `output_format`: string ['jpeg', 'png', 'webp'] =png
- `thinking_level`: string/null ['minimal', 'medium', 'high'] =medium
- `safety_tolerance`: string ['1', '2', '3', '4', '5', '6'] =4
- `sync_mode`: boolean =False
- `system_prompt`: string =
- `num_images`: integer =1

## `google/nano-banana-2.1/edit`

Returns: images, description

- `image_urls`: array
- `limit_generations`: boolean =True
- `pdf_url`: string/null
- `video_url`: string/null
- `thinking_level`: string/null ['minimal', 'medium', 'high'] =medium
- `resolution`: string ['1K', '2K', '4K'] =1K
- `prompt`: *string
- `output_format`: string ['jpeg', 'png', 'webp'] =png
- `num_images`: integer =1
- `enable_web_search`: boolean =False
- `aspect_ratio`: string/null ['auto', '21:9', '16:9', '3:2', '4:3', '5:4', '1:1', '4:5'] =auto
- `seed`: integer/null
- `safety_tolerance`: string ['1', '2', '3', '4', '5', '6'] =4
- `sync_mode`: boolean =False
- `system_prompt`: string =

## `xai/grok-imagine-image/v2.0/text-to-image`

Returns: images, revised_prompt

- `prompt`: *string
- `aspect_ratio`: string ['2:1', '20:9', '19.5:9', '16:9', '4:3', '3:2', '1:1', '2:3'] =1:1
- `resolution`: string ['1k', '1.5k', '2k'] =1k
- `enable_safety_checker`: boolean =True
- `output_format`: string ['jpeg', 'png', 'webp'] =jpeg
- `quality`: string ['low', 'medium', 'auto'] =medium
- `sync_mode`: boolean =False
- `num_images`: integer =1

## `xai/grok-imagine-image/v2.0/edit`

Returns: images, revised_prompt

- `image_urls`: array
- `prompt`: *string
- `aspect_ratio`: string ['2:1', '20:9', '19.5:9', '16:9', '4:3', '3:2', '1:1', '2:3'] =auto
- `resolution`: string ['1k', '1.5k', '2k'] =1k
- `enable_safety_checker`: boolean =True
- `output_format`: string ['jpeg', 'png', 'webp'] =jpeg
- `quality`: string ['low', 'medium', 'auto'] =medium
- `sync_mode`: boolean =False
- `num_images`: integer =1

## `blackforestlabs/flux-3/klein/text-to-image`

Returns: has_nsfw_concepts, prompt, timings, seed, images

- `sync_mode`: boolean =False
- `output_format`: string ['jpeg', 'png', 'webp'] =png
- `enable_prompt_expansion`: boolean =True
- `prompt`: *string
- `bounding_boxes`: array/null
- `image_size`: ImageSize/string ['square_hd', 'square', 'portrait_4_3', 'portrait_16_9', 'landscape_4_3', 'landscape_16_9'] =square_hd
- `num_images`: integer =1
- `seed`: integer/null
- `enable_safety_checker`: boolean =True

## `blackforestlabs/flux-3/klein/edit-image`

Returns: has_nsfw_concepts, prompt, timings, seed, images

- `prompt`: *string
- `output_format`: string ['jpeg', 'png', 'webp'] =png
- `enable_prompt_expansion`: boolean =True
- `sync_mode`: boolean =False
- `bounding_boxes`: array/null
- `image_size`: ImageSize/string/null ['square_hd', 'square', 'portrait_4_3', 'portrait_16_9', 'landscape_4_3', 'landscape_16_9']
- `image_urls`: *array
- `num_images`: integer =1
- `seed`: integer/null
- `enable_safety_checker`: boolean =True

## `blackforestlabs/flux-3/klein/text-to-image/lora`

Returns: has_nsfw_concepts, prompt, timings, seed, images

- `prompt`: *string
- `output_format`: string ['jpeg', 'png', 'webp'] =png
- `enable_prompt_expansion`: boolean =True
- `sync_mode`: boolean =False
- `loras`: array =[]
- `image_size`: ImageSize/string ['square_hd', 'square', 'portrait_4_3', 'portrait_16_9', 'landscape_4_3', 'landscape_16_9'] =square_hd
- `bounding_boxes`: array/null
- `num_images`: integer =1
- `seed`: integer/null
- `enable_safety_checker`: boolean =True

## `fal-ai/z-image/turbo`

Returns: seed, images, has_nsfw_concepts, prompt, timings

- `enable_safety_checker`: boolean =True
- `output_format`: string ['jpeg', 'png', 'webp'] =png
- `image_size`: ImageSize/string ['square_hd', 'square', 'portrait_4_3', 'portrait_16_9', 'landscape_4_3', 'landscape_16_9'] =landscape_4_3
- `seed`: integer/null
- `acceleration`: string ['none', 'regular', 'high'] =regular
- `enable_prompt_expansion`: boolean =False
- `sync_mode`: boolean =False
- `prompt`: *string
- `num_inference_steps`: integer =8
- `num_images`: integer =1

## `fal-ai/z-image/turbo/inpaint`

Returns: seed, images, has_nsfw_concepts, prompt, timings

- `seed`: integer/null
- `control_start`: number =0
- `mask_image_url`: *string
- `acceleration`: string ['none', 'regular', 'high'] =regular
- `enable_prompt_expansion`: boolean =False
- `prompt`: *string
- `num_images`: integer =1
- `strength`: number =1
- `output_format`: string ['jpeg', 'png', 'webp'] =png
- `image_size`: ImageSize/string ['square_hd', 'square', 'portrait_4_3', 'portrait_16_9', 'landscape_4_3', 'landscape_16_9', 'auto'] =auto
- `enable_safety_checker`: boolean =True
- `control_scale`: number =0.75
- `control_end`: number =0.8
- `sync_mode`: boolean =False
- `image_url`: *string
- `num_inference_steps`: integer =8

## `google/gemini-omni-flash/v1.2/text-to-video`

Returns: video

- `prompt`: *string
- `resolution`: string ['360p', '720p', '1080p', '4k'] =720p
- `duration`: integer =8
- `aspect_ratio`: string ['16:9', '9:16'] =16:9

## `google/gemini-omni-flash/v1.2/image-to-video`

Returns: video

- `prompt`: *string
- `resolution`: string ['360p', '720p', '1080p', '4k'] =720p
- `duration`: integer =8
- `aspect_ratio`: string ['16:9', '9:16'] =16:9
- `end_image_url`: string/null
- `image_url`: *string

## `google/gemini-omni-flash/v1.2/extend`

Returns: video

- `prompt`: *string
- `resolution`: string ['360p', '720p', '1080p', '4k'] =720p
- `duration`: integer =8
- `video_url`: *string

## `bytedance/seedance-2.5/us/text-to-video`

Returns: seed, video, draft_id

- `resolution`: string ['480p', '720p', '1080p'] =720p
- `end_user_id`: string/null
- `bitrate_mode`: string ['standard', 'high'] =standard
- `prompt`: *string
- `generate_audio`: boolean =True
- `duration`: string ['auto', '4', '5', '6', '7', '8', '9', '10'] =auto
- `draft`: boolean =False
- `codec`: string ['auto', 'H264', 'H265'] =auto
- `aspect_ratio`: string ['auto', '21:9', '16:9', '4:3', '1:1', '3:4', '9:16'] =auto

## `bytedance/seedance-2.5/us/image-to-video`

Returns: seed, video, draft_id

- `prompt`: string/null
- `resolution`: string ['480p', '720p', '1080p'] =720p
- `end_user_id`: string/null
- `bitrate_mode`: string ['standard', 'high'] =standard
- `end_image_url`: string/null
- `image_url`: *string
- `generate_audio`: boolean =True
- `duration`: string ['auto', '4', '5', '6', '7', '8', '9', '10'] =auto
- `draft`: boolean =False
- `codec`: string ['auto', 'H264', 'H265'] =auto
- `aspect_ratio`: string =auto

## `minimax/h3-max/text-to-video`

Returns: video, expanded_prompt, timings

- `resolution`: string ['480P', '768P', '1080P'] =768P
- `prompt_expansion_mode`: *string =balanced
- `aspect_ratio`: string ['21:9', '16:9', '4:3', '1:1', '3:4', '9:16'] =16:9
- `sync_mode`: boolean =False
- `duration`: number =5
- `seed`: integer/null
- `target_audio_url`: string/null
- `prompt`: *string
- `enable_safety_checker`: boolean =True

## `minimax/h3-max/image-to-video`

Returns: video, expanded_prompt, timings

- `image_url`: string/null
- `resolution`: string ['480P', '768P', '1080P'] =768P
- `prompt_expansion_mode`: *string =balanced
- `end_image_url`: string/null
- `sync_mode`: boolean =False
- `duration`: number =5
- `seed`: integer/null
- `target_audio_url`: string/null
- `prompt`: *string
- `enable_safety_checker`: boolean =True

## `minimax/h3-max/extend-video`

Returns: video, duration, seed, source, expanded_prompt, timings

- `resolution`: string ['480P', '768P', '1080P', '2K'] =768P
- `output`: string ['extended', 'continuation'] =extended
- `aspect_ratio`: string ['auto', '21:9', '16:9', '4:3', '1:1', '3:4', '9:16'] =auto
- `duration`: number =5
- `seed`: integer/null
- `video_url`: *string
- `prompt`: *string
- `enable_prompt_expansion`: boolean =True
- `enable_safety_checker`: boolean =True
- `reference_audio_urls`: array

## `minimax/h3-max-turbo/text-to-video`

Returns: video, expanded_prompt, timings

- `resolution`: string ['480P', '768P', '1080P'] =768P
- `prompt_expansion_mode`: *string =balanced
- `aspect_ratio`: string ['21:9', '16:9', '4:3', '1:1', '3:4', '9:16'] =16:9
- `sync_mode`: boolean =False
- `duration`: number =5
- `seed`: integer/null
- `target_audio_url`: string/null
- `prompt`: *string
- `enable_safety_checker`: boolean =True

## `minimax/h3-max-turbo/image-to-video`

Returns: video, expanded_prompt, timings

- `image_url`: string/null
- `resolution`: string ['480P', '768P', '1080P'] =768P
- `prompt_expansion_mode`: *string =balanced
- `end_image_url`: string/null
- `sync_mode`: boolean =False
- `duration`: number =5
- `seed`: integer/null
- `target_audio_url`: string/null
- `prompt`: *string
- `enable_safety_checker`: boolean =True

## `minimax/h3-max-turbo/extend-video`

Returns: video, duration, seed, source, expanded_prompt, timings

- `resolution`: string ['480P', '768P', '1080P', '2K'] =768P
- `output`: string ['extended', 'continuation'] =extended
- `aspect_ratio`: string ['auto', '21:9', '16:9', '4:3', '1:1', '3:4', '9:16'] =auto
- `duration`: number =5
- `seed`: integer/null
- `video_url`: *string
- `prompt`: *string
- `enable_prompt_expansion`: boolean =True
- `enable_safety_checker`: boolean =True
- `reference_audio_urls`: array

## `xai/grok-imagine-video/v1.5/lite/text-to-video`

Returns: video

- `enable_safety_checker`: boolean =True
- `prompt`: *string
- `aspect_ratio`: string ['16:9', '4:3', '3:2', '1:1', '2:3', '3:4', '9:16'] =16:9
- `resolution`: string ['480p', '720p', '1080p'] =720p
- `duration`: integer =6

## `xai/grok-imagine-video/v1.5/lite/image-to-video`

Returns: video

- `enable_safety_checker`: boolean =True
- `prompt`: *string
- `image_url`: *string
- `resolution`: string ['480p', '720p', '1080p'] =720p
- `duration`: integer =6

## `elevenlabs/tts/eleven-v4`

Returns: audio, timestamps

- `similarity_boost`: number =0.75
- `timestamps`: boolean =False
- `seed`: integer/null
- `enable_safety_checker`: boolean =True
- `output_format`: string ['mp3_22050_32', 'mp3_44100_32', 'mp3_44100_64', 'mp3_44100_96', 'mp3_44100_128', 'mp3_44100_192', 'pcm_8000', 'pcm_16000'] =mp3_44100_128
- `language_code`: string/null
- `apply_text_normalization`: string ['auto', 'on', 'off'] =auto
- `text`: *string
- `voice`: string =Rachel
- `stability`: number =0.5

## `google/gemini-3.8-flash-tts`

Returns: audio

- `prompt`: string/null
- `turns`: array/null
- `speakers`: array/null
- `enable_safety_checker`: boolean =True
- `voice`: string ['Achernar', 'Achird', 'Algenib', 'Algieba', 'Alnilam', 'Aoede', 'Autonoe', 'Callirrhoe'] =Kore
- `style_instructions`: string/null

## `fal-ai/chatterbox/text-to-speech/multilingual`

Returns: audio

- `enable_safety_checker`: boolean =True
- `text`: *string
- `custom_audio_language`: string/null ['english', 'arabic', 'danish', 'german', 'greek', 'spanish', 'finnish', 'french']
- `exaggeration`: number =0.5
- `voice`: string =english
- `temperature`: number =0.8
- `seed`: integer/null
- `cfg_scale`: number =0.5

## `fal-ai/qwen-3-tts/clone-voice/1.7b`

Returns: speaker_embedding

- `audio_url`: *string
- `reference_text`: string/null
- `enable_safety_checker`: boolean =True

## `fal-ai/minimax/voice-clone`

Returns: custom_voice_id, audio

- `audio_url`: *string
- `accuracy`: number/null
- `model`: string ['speech-02-hd', 'speech-02-turbo', 'speech-01-hd', 'speech-01-turbo'] =speech-02-hd
- `enable_safety_checker`: boolean =True
- `noise_reduction`: boolean =False
- `need_volume_normalization`: boolean =False
- `text`: string/null =Hello, this is a preview of your cloned voice! I hope you like it!

## `fal-ai/qwen-3-tts/voice-design/1.7b`

Returns: audio

- `max_new_tokens`: integer/null =200
- `prompt`: *string
- `repetition_penalty`: number/null =1.05
- `text`: *string
- `top_k`: integer/null =50
- `subtalker_top_k`: integer/null =50
- `subtalker_top_p`: number/null =1
- `subtalker_temperature`: number/null =0.9
- `subtalker_dosample`: boolean/null =True
- `temperature`: number/null =0.9
- `top_p`: number/null =1
- `language`: string ['Auto', 'English', 'Chinese', 'Spanish', 'French', 'German', 'Italian', 'Japanese'] =Auto
- `enable_safety_checker`: boolean =True

## `fal-ai/minimax/voice-design`

Returns: custom_voice_id, audio

- `preview_text`: *string
- `prompt`: *string
- `enable_safety_checker`: boolean =True

## `fal-ai/elevenlabs/speech-to-text/scribe-v2`

Returns: language_code, language_probability, text, words

- `language_code`: string/null
- `audio_url`: *string
- `tag_audio_events`: boolean =True
- `diarize`: boolean =True
- `keyterms`: array =[]

## `nvidia/nemotron-asr-multilingual/asr`

Returns: output, partial

- `audio_url`: *string
- `language`: string ['auto', 'en-US', 'en-GB', 'es-US', 'es-ES', 'de-DE', 'fr-FR', 'fr-CA'] =auto
- `acceleration`: string ['none', 'regular', 'high', 'full'] =regular

## `fal-ai/wizper`

Returns: languages, text, chunks

- `merge_chunks`: boolean =True
- `max_segment_len`: integer =29
- `task`: string ['transcribe', 'translate'] =transcribe
- `audio_url`: *string
- `language`: string/null ['af', 'am', 'ar', 'as', 'az', 'ba', 'be', 'bg'] =en
- `chunk_level`: string =segment
- `version`: string =3

## `fal-ai/elevenlabs/voice-changer`

Returns: audio, seed

- `seed`: integer
- `style`: number/null
- `output_format`: string ['mp3_22050_32', 'mp3_44100_32', 'mp3_44100_64', 'mp3_44100_96', 'mp3_44100_128', 'mp3_44100_192', 'pcm_8000', 'pcm_16000'] =mp3_44100_128
- `model_id`: string ['eleven_multilingual_sts_v2', 'eleven_english_sts_v2'] =eleven_multilingual_sts_v2
- `use_speaker_boost`: boolean/null
- `remove_background_noise`: boolean =False
- `audio_url`: *string
- `stability`: number/null
- `voice`: string =Rachel
- `similarity_boost`: number/null

## `resemble-ai/chatterboxhd/speech-to-speech`

Returns: audio

- `high_quality_audio`: boolean =False
- `target_voice_audio_url`: string
- `source_audio_url`: *string
- `target_voice`: string ['Aurora', 'Blade', 'Britney', 'Carl', 'Cliff', 'Richard', 'Rico', 'Siobhan']

## `fal-ai/chatterbox/speech-to-speech`

Returns: audio

- `source_audio_url`: *string
- `target_voice_audio_url`: string/null

## `elevenlabs/music/v2.5`

Returns: audio

- `seed`: integer/null
- `force_instrumental`: boolean =False
- `music_length_ms`: integer/null
- `output_format`: string ['mp3_22050_32', 'mp3_24000_48', 'mp3_44100_32', 'mp3_44100_64', 'mp3_44100_96', 'mp3_44100_128', 'mp3_44100_192', 'mp3_48000_128'] =mp3_48000_192
- `enable_safety_checker`: boolean =True
- `prompt`: string/null
- `composition_plan`: MusicV2CompositionPlan/null

## `minimax/music-3`

Returns: seed, duration, audio

- `guidance_scale`: number =1.7
- `prompt`: *string
- `duration`: number =60
- `enable_safety_checker`: boolean =True
- `lyrics`: *string
- `num_inference_steps`: integer =30
- `seed`: integer/null

## `mureka/v9.5/generate/song`

Returns: audio, song_id, lyrics_sections, duration

- `reference_id`: string/null
- `vocal_id`: string/null
- `enable_safety_checker`: boolean =True
- `melody_id`: string/null
- `duration`: integer/null
- `styles`: array/null
- `prompt`: string/null
- `lyrics`: string/null
- `gender`: string/null ['female', 'male']

## `elevenlabs/sound-effects/v3`

Returns: audio

- `enable_safety_checker`: boolean =True
- `output_format`: string ['mp3_22050_32', 'mp3_44100_32', 'mp3_44100_64', 'mp3_44100_96', 'mp3_44100_128', 'mp3_44100_192', 'pcm_8000', 'pcm_16000'] =mp3_44100_128
- `prompt_influence`: number =0.3
- `loop`: boolean =False
- `duration_seconds`: number/null
- `text`: *string

## `mirelo-ai/sfx2.0/text-to-audio`

Returns: audio, model, seeds

- `upload_audio_bitrate_kbps`: integer/null
- `negative_prompt`: string/null
- `seed`: integer/null
- `num_samples`: integer =2
- `prompt`: *string
- `upload_audio_format`: string ['wav', 'mp3', 'aac', 'flac'] =wav
- `duration`: number =30

## `fal-ai/stable-audio-3/small/sfx/text-to-audio`

Returns: seed, audio, prompt

- `seed`: integer/null
- `prompt`: *string
- `sync_mode`: boolean =False
- `num_inference_steps`: integer =8
- `guidance_scale`: number =1
- `output_format`: string ['mp3', 'wav', 'flac', 'ogg', 'opus', 'm4a', 'aac'] =mp3
- `bitrate`: string =192k
- `duration`: number =30
- `enable_prompt_expansion`: boolean =False
- `negative_prompt`: string =
- `enable_safety_checker`: boolean =True

## `fal-ai/demucs`

Returns: bass, drums, vocals, piano, guitar, other

- `model`: string ['htdemucs', 'htdemucs_ft', 'htdemucs_6s', 'hdemucs_mmi', 'mdx', 'mdx_extra', 'mdx_q', 'mdx_extra_q'] =htdemucs_6s
- `segment_length`: integer/null
- `output_format`: string ['wav', 'mp3'] =mp3
- `stems`: array/null =['vocals', 'drums', 'bass', 'other', 'guitar', 'piano']
- `audio_url`: *string
- `shifts`: integer =1
- `overlap`: number =0.25

## `fal-ai/sam-audio/separate`

Returns: duration, target, sample_rate, residual

- `max_chunk_duration`: number =60
- `reranking_candidates`: integer =1
- `output_format`: string ['wav', 'mp3'] =wav
- `chunk_overlap`: number =5
- `acceleration`: string ['fast', 'balanced', 'quality'] =balanced
- `audio_url`: *string
- `predict_spans`: boolean =False
- `prompt`: *string

## `mureka/api/song/stem`

Returns: midi_zip_url, zip_url

- `audio_url`: *string
- `model`: string ['audio-separation-1', 'audio-separation-2', 'audio-separation-3'] =audio-separation-3

## `fal-ai/ace-step/audio-inpaint`

Returns: seed, tags, lyrics, audio

- `variance`: number =0.5
- `granularity_scale`: integer =10
- `lyric_guidance_scale`: number =1.5
- `guidance_interval_decay`: number =0
- `end_time`: number =30
- `end_time_relative_to`: string ['start', 'end'] =start
- `start_time_relative_to`: string ['start', 'end'] =start
- `guidance_interval`: number =0.5
- `audio_url`: *string
- `minimum_guidance_scale`: number =3
- `guidance_scale`: number =15
- `start_time`: number =0
- `lyrics`: string =
- `tag_guidance_scale`: number =5
- `guidance_type`: string ['cfg', 'apg', 'cfg_star'] =apg
- `seed`: integer/null
- `enable_safety_checker`: boolean =True
- `tags`: *string
- `number_of_steps`: integer =27
- `scheduler`: string ['euler', 'heun'] =euler

## `fal-ai/stable-audio-3/medium/audio-inpainting`

Returns: seed, audio, prompt

- `seed`: integer/null
- `prompt`: *string
- `sync_mode`: boolean =False
- `guidance_scale`: number =1
- `mask_start_seconds`: *number
- `output_format`: string ['mp3', 'wav', 'flac', 'ogg', 'opus', 'm4a', 'aac'] =mp3
- `num_inference_steps`: integer =8
- `audio_url`: *string
- `negative_prompt`: string =
- `bitrate`: string =192k
- `enable_prompt_expansion`: boolean =False
- `mask_end_seconds`: *number
- `enable_safety_checker`: boolean =True

## `mureka/api/song/edit`

Returns: audio, song_id, lyrics_sections, duration

- `edit_end`: *integer
- `song_id`: string/null
- `upload_audio_id`: string/null
- `edit_start`: *integer
- `enable_safety_checker`: boolean =True
- `lyrics`: *string

## `fal-ai/hunyuan-3d/v3.1/pro/image-to-3d`

Returns: model_urls, seed, thumbnail, model_glb

- `left_image_url`: string/null
- `right_front_image_url`: string/null
- `generate_type`: string ['Normal', 'Geometry'] =Normal
- `top_image_url`: string/null
- `input_image_url`: *string
- `back_image_url`: string/null
- `enable_pbr`: boolean =False
- `face_count`: integer =500000
- `bottom_image_url`: string/null
- `left_front_image_url`: string/null
- `right_image_url`: string/null

## `fal-ai/trellis-2`

Returns: model_glb

- `tex_slat_guidance_interval_start`: number =0.6
- `shape_slat_guidance_strength`: number =7.5
- `ss_guidance_strength`: number =7.5
- `remesh_project`: number =0
- `uv_unwrap_global_iterations`: integer =1
- `remesh`: boolean =True
- `shape_slat_guidance_rescale`: number =0.5
- `shape_slat_guidance_interval_end`: number =1
- `decimation_target`: integer =500000
- `uv_unwrap_refine_iterations`: integer =0
- `texture_size`: integer [1024, 2048, 4096] =2048
- `image_url`: *string
- `shape_slat_sampling_steps`: integer =12
- `uv_unwrap_smooth_strength`: number =1
- `ss_guidance_interval_end`: number =1
- `tex_slat_sampling_steps`: integer =12
- `tex_slat_guidance_interval_end`: number =0.9
- `uv_unwrap_angle_threshold_deg`: number =90
- `ss_guidance_interval_start`: number =0.6
- `shape_slat_guidance_interval_start`: number =0.6
- `resolution`: integer [512, 1024, 1536] =1024
- `ss_guidance_rescale`: number =0.7
- `tex_slat_guidance_strength`: number =1
- `tex_slat_rescale_t`: number =3
- `shape_slat_rescale_t`: number =3
- `tex_slat_guidance_rescale`: number =0
- `ss_rescale_t`: number =5
- `ss_sampling_steps`: integer =12
- `seed`: integer/null
- `remesh_band`: number =1

## `blackforestlabs/flux-3/klein/base/trainer`

Returns: config_file, lora_file

- `trigger_phrase`: string =
- `images_data_url`: *string
- `resolution`: integer [512, 768, 1024] =1024
- `learning_rate`: number =0.0001
- `steps`: integer =1000
- `enable_safety_checker`: boolean =True

## `fal-ai/z-image-trainer`

Returns: config_file, diffusers_lora_file

- `image_data_url`: *string
- `steps`: integer =1000
- `training_type`: string ['content', 'style', 'balanced'] =balanced
- `default_caption`: string/null
- `learning_rate`: number =0.0001
- `enable_safety_checker`: boolean =True

## `fal-ai/ltx23-video-trainer`

Returns: video, debug_dataset, config_file, lora_file

- `training_data_url`: *string
- `validation`: array =[]
- `with_audio`: boolean/null
- `resolution`: string ['low', 'medium', 'high'] =medium
- `split_input_duration_threshold`: number =30
- `stg_scale`: number =1
- `aspect_ratio`: string ['16:9', '1:1', '9:16'] =1:1
- `debug_dataset`: boolean =False
- `validation_negative_prompt`: string =worst quality, inconsistent motion, blurry, jittery, distorted
- `rank`: integer [8, 16, 32, 64, 128] =32
- `validation_frame_rate`: integer =25
- `learning_rate`: number =0.0002
- `frame_rate`: integer =25
- `audio_preserve_pitch`: boolean =True
- `generate_audio_in_validation`: boolean =True
- `number_of_frames`: integer =89
- `validation_aspect_ratio`: string ['16:9', '1:1', '9:16'] =1:1
- `trigger_phrase`: string =
- `validation_number_of_frames`: integer =89
- `auto_scale_input`: boolean =False
- `split_input_into_scenes`: boolean =True
- `number_of_steps`: integer =2000
- `validation_resolution`: string ['low', 'medium', 'high'] =high
- `first_frame_conditioning_p`: number =0.5
- `audio_normalize`: boolean =True

## `minimax/h3/t2v/trainer`

Returns: lora_file, config_file, debug_dataset

- `rank`: integer [8, 16, 32, 64, 128] =32
- `number_of_frames`: integer =73
- `trigger_phrase`: string =
- `number_of_steps`: integer =2000
- `aspect_ratio`: string ['21:9', '16:9', '4:3', '1:1', '3:4', '9:16'] =16:9
- `auto_scale_input`: boolean =False
- `strict_dataset`: boolean =False
- `debug_dataset`: boolean =False
- `split_input_duration_threshold`: number =30
- `resolution`: string ['low', 'medium', 'high'] =medium
- `split_input_into_scenes`: boolean =True
- `first_frame_conditioning_p`: number =0
- `training_data_url`: *string
- `learning_rate`: number =0.0002
- `frame_rate`: integer =24
