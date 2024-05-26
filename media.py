import os
import cv2
import asyncio
import tempfile
import random
import requests
import subprocess
import shlex
import json
from logger_manager import logger
from human_id import generate_id

from moviepy.editor import VideoFileClip, ImageClip, CompositeVideoClip, TextClip, AudioFileClip
from datetime import datetime

from s3 import read_file, write_file

from openai import OpenAI
openai_client = OpenAI(api_key=os.getenv('OPENAI_API_KEY', default=None))

time_passed = 0
last_request_time = None

from requests.adapters import HTTPAdapter, Retry
s = requests.Session()


async def overlay_b_roll(aws_key, extension, b_roll_to_overlay, transcript_lines):

    global last_request_time
    last_request_time = datetime.now()


    logger.debug(f'Overlaying b-roll on {aws_key}, with {extension}')
    # try:


    media_file = await read_file(aws_key)
    clip = None
    protect_ends = True
    if 'video' in extension:
        processed_file = tempfile.NamedTemporaryFile( delete=True)
    elif 'audio' in extension:
        processed_file = tempfile.NamedTemporaryFile( delete=True)
    # else:
    #     # Handle other file types or raise an error if unsupported type.
    #     processed_file = None

    processed_file.write(media_file)
    composites = []
    clip_audio = None
    clip_duration = 0
    clip_size = None

    if 'video' in extension:

        clip = VideoFileClip(processed_file.name)
        rotated = await is_rotated(processed_file.name)
        if rotated:
            clip = clip.resize(clip.size[::-1])

        clip_audio = clip.audio
        clip_duration = clip.duration
        clip_size = clip.size
        clip_dimensions = clip.get_frame(0).shape
        layout = await determine_orientation(clip_dimensions)
        composites.append(clip)

    else :
        # create placeholder clip for audio
        clip_audio = AudioFileClip(processed_file.name)
        clip_duration = clip_audio.duration
        # clip = AudioFileClip(processed_file.name)
        #set to 1080 x 1920
        clip_size = 360, 640
        protect_ends = False 

        clip_dimensions =  640, 360, 1
        layout = 'vertical'

    
    
    tasks = []
    logger.debug(f'Processing {len(b_roll_to_overlay)} b-roll clips')
    for b_roll in b_roll_to_overlay:
        prompt = b_roll['prompt']   
        logger.debug(f'Processing b-roll object: {b_roll}')
        if not b_roll.get('media_key'):      
            logger.debug(f'Generating image for prompt: {prompt}')      
            task = asyncio.create_task(generate_temp_image(prompt))
            tasks.append(task)
        else:
            logger.debug(f'Using existing image for prompt: {prompt}')
            media_key = b_roll['media_key']
            try:
                task = asyncio.create_task(get_image_from_s3(prompt, media_key))

            except Exception as e:
                logger.error(f'Error reading file {media_key} from S3')
    logger.debug('Awaiting image generation')
    time_passed = 0
    images = await asyncio.gather(*tasks)
    # print('images', images)
    for image in images:
        if image:
            prompt = image['prompt']
            for b_roll in b_roll_to_overlay:
                if b_roll['prompt'] == prompt:
                    b_roll['file'] = image.get('file')
                    b_roll['media_key'] = image.get('media_key')
                    b_roll['media_url'] = image.get('media_url')
                    break


    counter = 0
    for b_roll in b_roll_to_overlay:
        logger.debug(f'doing b-roll transform: {b_roll}')
        prompt = b_roll['prompt']   
        processed_image = b_roll.get('file')
        b_roll['file'] = None
        counter += 1

        try:
            if not processed_image:
                logger.error(f'No image found for prompt: {prompt}')
                continue
            if processed_image :
                logger.debug(f'Processing b-roll image: {prompt} with file {processed_image.name}')

                start, end = b_roll['start'], b_roll['end']
                try:
                    start = datetime.strptime(start, '%H:%M:%S.%f')
                    end = datetime.strptime(end, '%H:%M:%S.%f')
                except:
                    start = datetime.strptime(start, '%H:%M:%S')
                    end = datetime.strptime(end, '%H:%M:%S')

                #get as  time delta
                if not protect_ends: # stupid as fuck designator for if its audio or video - this is audio
                    if counter == 1:
                        start = datetime.strptime('00:00:00.000', '%H:%M:%S.%f')
                    if counter >= len(b_roll_to_overlay):
                        # end = clip_duration
                        # datetime.date(end)
                        logger.debug('last clip')
                        # eZprint_anything(['on last clip',len(b_roll_to_overlay)], ['OVERLAY'], line_break=True)
                    else:
                        end = b_roll_to_overlay[counter]['start']
                        # eZprint_anything(['not last clip',len(b_roll_to_overlay), end], ['OVERLAY'], line_break=True)
                        try:
                            end = datetime.strptime(end, '%H:%M:%S.%f')
                        except:
                            end = datetime.strptime(end, '%H:%M:%S')

                        
                duration = end - start
                duration = duration.total_seconds() 

                start_delta = start - datetime.strptime('00:00:00.000', '%H:%M:%S.%f')
                start = start_delta.total_seconds()

                if not protect_ends and counter >= len(b_roll_to_overlay):
                    duration = clip_duration - start

                if protect_ends:
                    if duration < 5:
                        duration = 5
                    if start < 3:
                        # break out of this image
                        continue 
                    if start > clip_duration-2:
                        # break out of this image
                        # duration = 3
                        continue
                
                image = cv2.imread(processed_image.name)
                # processed_image.close() 

                if layout == 'horizontal':
                    # Resize image based on orientation of clip
                    resized_image = cv2.resize(image, (clip_dimensions[1], clip_dimensions[1]*image.shape[0]//image.shape[1]))
                    clip_widest = clip_dimensions[1]
                else:
                    resized_image = cv2.resize(image, (clip_dimensions[0]*image.shape[1]//image.shape[0], clip_dimensions[0]))
                    clip_widest = clip_dimensions[0]

                # print('Resized image size:', resized_image.shape)
                # print('Resized image size:', resized_image.shape)
                # # Crop excess width/height if necessary
                start_x = max(0, (resized_image.shape[1] - clip_dimensions[1]) // 2)
                start_y = max(0, (resized_image.shape[0] - clip_dimensions[0]) // 2)

                resized_image = cv2.cvtColor(resized_image, cv2.COLOR_BGR2RGB)

                image_clip = ImageClip(resized_image)
                image_clip = image_clip.set_duration(duration)
                image_clip = image_clip.set_start(start)
                #set default position
                image_clip = image_clip.set_position('center')

                if 'position' in b_roll:
                    # eZprint('position found', DEBUG_KEYS)
                    image_clip = image_clip.set_position(b_roll['position'])

                if 'fade' in b_roll:
                    fadein_duration = float(b_roll['fade'].get('fadein', 0))
                    fadeout_duration = float(b_roll['fade'].get('fadeout', 0))
                    if fadein_duration:
                        image_clip = image_clip.crossfadein(fadein_duration)
                    if fadeout_duration:
                        image_clip = image_clip.crossfadeout(fadeout_duration)


                scale_modifier = clip_widest / 640
                pixels_per_second = 75 * scale_modifier
                # eZprint(f'pixels per second {pixels_per_second}', DEBUG_KEYS)
                
                width_pixels_to_cover_ps = (((resized_image.shape[1]/clip_dimensions[1] ) - 1 )/ duration) * clip_dimensions[1]

                if width_pixels_to_cover_ps < pixels_per_second:
                    pixels_per_second = width_pixels_to_cover_ps

                directions = ['left', 'right']
                #choose random direction
                direction = random.choice(directions)   

                if 'pan' in b_roll:
                    if b_roll['pan'] == 'left':
                        direction = 'left'
                    elif b_roll['pan'] == 'right':
                        direction = 'right'

                if direction == 'left':
                    start_position = 0
                    end_position = -start_x*2

                    image_clip = image_clip.set_position(
                        lambda t, start_position=start_position, end_position=end_position, pixels_per_second=pixels_per_second, direction=direction: 
                        (calculate_pan_position(t, direction, start_position, end_position, pixels_per_second), 'center')
                    )

                elif direction == 'right':
                    start_position = -start_x*2
                    end_position = 0

                    image_clip = image_clip.set_position(
                        lambda t, start_position=start_position, end_position=end_position, pixels_per_second=pixels_per_second, direction=direction: 
                        (calculate_pan_position(t, direction, start_position, end_position, pixels_per_second), 'center')
                    )
                    
                    image_clip = image_clip.set_position(
                        lambda t, start_position=start_position, end_position=end_position, pixels_per_second=pixels_per_second, direction=direction: 
                        (calculate_pan_position(t, direction, start_position, end_position, pixels_per_second), 'center')
                    )
                    

                composites.append(image_clip)
        except Exception as e:
            logger.error(f'Error processing b-roll image: {str(e)}')
            continue
    if transcript_lines:
        transcript_lines.sort(key=lambda x: x['chunkID'])
        for line in transcript_lines:
            # eZprint_anything([line], ['OVERLAY'])
            start = line['start']
            end = line['end']
            try:
                start = datetime.strptime(start, '%H:%M:%S.%f')
                end = datetime.strptime(end, '%H:%M:%S.%f')
            except:
                start = datetime.strptime(start, '%H:%M:%S')
                end = datetime.strptime(end, '%H:%M:%S')
            #get as  time delta
            duration = end - start
            duration = duration.total_seconds()
            text = line.get('text', '')

            ## splits lines up by appostrophe or and divides timestamp and time between them based on sections
    
            # eZprint_anything([text], ['OVERLAY', 'TRANSCRIBE'])
            ## checks if any line has more than 5 words and if so splits it up into sections

            # lines_split_by_apostophe = []
            
            # for new_line in lines_split_by_word_count:
            #     eZprint('checking for apostrophe', ['OVERLAY', 'TRANSCRIBE'])
            #     new_line_sections = new_line.split(',')
            #     eZprint_anything([new_line_sections], ['OVERLAY'], line_break=True)
            #     if len(new_line_sections) > 1:
            #         eZprint('found apostrophe', ['OVERLAY', 'TRANSCRIBE'])
            #         for new_line_section in new_line_sections:
            #             if new_line_section != '':
            #                 lines_split_by_apostophe.append(new_line_section)
            #     else:
            #         lines_split_by_apostophe.append(new_line)
            
            # eZprint('running line list', ['OVERLAY', 'TRANSCRIBE'])
            # eZprint_anything([lines_split_by_apostophe], ['OVERLAY'], line_break=True)
                        
            # get total characters in line by finding how many newlines were added, 
            lines_split_by_word_count = []
            total_lines = 0
            if len(text.split(' ')) > 2:
                # eZprint('splitting line as over 2', ['OVERLAY', 'TRANSCRIBE'])
                split_text = text.split(' ')
                word_count = len(split_text)
                lines_needed = word_count / 2
                # round up to int
                lines_needed = int(lines_needed) 

                # eZprint(f'lines needed {lines_needed}', ['OVERLAY', 'TRANSCRIBE'])
                if lines_needed > 1:    
                    wpl = int(len(split_text) / lines_needed)
                    # eZprint(f'words per line {wpl}', ['OVERLAY', 'TRANSCRIBE'])
                    for i in range(lines_needed):
                        new_line = ' '.join(split_text[i * wpl:(i * wpl)+wpl])
                        # lines_split_by_word_count.append(new_line)
                        ## if last line add the rest of the words
                        if i == lines_needed - 1:
                            new_line += " "
                            new_line += ' '.join(split_text[(i * wpl)+wpl:])
                        lines_split_by_word_count.append(new_line)
                        total_lines += 1
                else:
                    lines_split_by_word_count.append(text)
                    total_lines += 1
            else:
                lines_split_by_word_count.append(text)
                total_lines += 1
        
            # eZprint_anything([lines_split_by_word_count], ['OVERLAY', 'TRANSCRIBE'], line_break=True)

            
            line_characters = len(text) - (len(lines_split_by_word_count) - len(lines_split_by_word_count) ) + 1
            start_delta = start - datetime.strptime('00:00:00.000', '%H:%M:%S.%f')
            start = start_delta.total_seconds()
            running_progress = start

            # eZprint(f'line characters {line_characters}', ['OVERLAY', 'TRANSCRIBE'])

            # for line in lines_split_by_apostophe:
            #     eZprint_anything([line], ['OVERLAY'], line_break=True)
            #     # line_section_duration = duration / len(line_sections)

            #     if line != '':

            if os.getenv('DEBUG_SPLIT_BY_WORDS', default=None) == 'True':
                line_percent = 1/total_lines

            for line in lines_split_by_word_count:
                if line != '':
                    if not os.getenv('DEBUG_SPLIT_BY_WORDS', default=None) == 'True':
                        line_percent = len(line) / line_characters
                    line_duration = duration * line_percent
                    line_start = running_progress
                    line_end = line_start + line_duration
                    # duration_modifier = line_duration * .1
                    running_progress = line_end
                    text = line.strip()
                    size = clip_dimensions[1]* .8, None
                    # if os.getenv('DEBUG_LABEL', default=None) == 'True':
                    #     text_clip = TextClip(text.upper(), size = size, fontsize=50, color='white', kerning = 5, method='label', align='west', font = 'Oswald-SemiBold', stroke_color='black', stroke_width=1)
                    # else:

                    ## set font size dynamically based on screen resolution

                    screen_mod = (size[0] + size[0]) / (1920+1080)
                    font_size = int(os.getenv('DEBUG_FONT_SIZE', default=200))
                    font_type = os.getenv('DEBUG_FONT_TYPE', default='Barlow-Bold')
                    font_size = font_size * screen_mod
                    stroke_width = 4 * screen_mod
                    interline = -20 * screen_mod
                    kerning = 2 * screen_mod

                    text_clip = TextClip(text.upper(), size = size, fontsize=font_size, color='white', kerning = kerning, method='caption', align='west', font = font_type, stroke_color='black', stroke_width=stroke_width, interline=interline)
                    # eZprint(TextClip.search(font_type, 'font'), ['OVERLAY', 'TRANSCRIBE'])
                    # eZprint(TextClip.list('font'), ['OVERLAY', 'TRANSCRIBE'])
                    text_clip = text_clip.set_duration(line_duration )
                    text_clip = text_clip.set_start(line_start )
                    # set position so its centered on x and 80% down on y
                    text_clip = text_clip.set_position((.1, 0.7), relative=True)
                    # eZprint(f'line start {line_start} line end {line_end} line duration {line_duration} line percent {line_percent}', ['OVERLAY', 'TRANSCRIBE'])
                    composites.append(text_clip)

    def get_composite_clip(composites, clip_size, clip_audio, processed_file_name):
        compositeClip = CompositeVideoClip(composites, size=clip_size)
        compositeClip.audio = clip_audio
        compositeClip.write_videofile(processed_file_name,  remove_temp=True, codec='libx264', audio_codec='aac', fps=24)
        return processed_file_name
    
    file_to_send =  tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    url = None
    try:
        composite_loop = asyncio.get_event_loop()
        file_name = await composite_loop.run_in_executor(None, lambda: get_composite_clip(composites, clip_size, clip_audio, file_to_send.name))
        new_key = generate_id()
        url = await write_file(file_to_send.file, new_key ) 
    except Exception as e:

        logger.error(f'Error creating composite clip: {str(e)}')
        # return {'status': 'error', 'message': str(e)}


    for b_roll in b_roll_to_overlay:
        if b_roll.get('file'):
            b_roll['file'].close()
            # delete file record
            del b_roll['file']
    payload = {'aws_key': new_key, 'media_url': url, 'b_roll': b_roll_to_overlay, 'transcript_lines': transcript_lines}
    # compositeClip.write_videofile(file_to_send.name,  remove_temp=True, codec='libx264', audio_codec='aac')
    # await websocket.send(json.dumps({'event': 'video_ready', 'payload': {'video_name': file_to_send.name}}))
    # final_clip.write_videofile("my_concatenation.mp4", fps=24, codec='libx264', audio_codec='aac')
    logger.debug(f'Successfully processed b-roll for {aws_key}')
    return payload
    # except Exception as e:  
    #     logger.error(f'Failed to process b-roll for {aws_key}: {str(e)}')
    #     return {'status': 'error', 'message': str(e), 'b_roll': b_roll_to_overlay, 'transcript_lines': transcript_lines}
       


    

async def generate_temp_image(prompt):
    DEBUG_KEYS = ['FILE_HANDLING', 'IMAGE_GENERATION']
    # eZprint(f'Generating image with prompt: {prompt}', DEBUG_KEYS)
    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: openai_client.images.generate(prompt=prompt,
        n=1,
        size='1024x1024',
        model='dall-e-3',
        ))

    except Exception as e:
        return {'prompt':prompt}

    
    image_url = response.data[0].url
    response = requests.get(image_url)
    processed_media = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    processed_media.write(response.content)
    processed_media.close()

    new_key = generate_id()
    url = await write_file(response.content, new_key )
    logger.debug(f'url for image: {url}')
    return {'prompt':prompt, 'file' : processed_media, 'media_url' : url, 'media_key': new_key}
    
async def get_image_from_s3(prompt, media_key):

    file = await read_file(media_key)
    logger.debug(f'Using existing image for prompt: {prompt} with file {file}')

    processed_media = tempfile.NamedTemporaryFile( delete=False)
    processed_media.write(file)
    return {'prompt':prompt, 'file' : processed_media}

def calculate_pan_position(t, direction, start_position, end_position, pixels_per_second):
    if direction == 'left':
        position = start_position - pixels_per_second * t
        # Clamp the position so that it does not go past the end_position
        clamped_position = max(end_position, position) 
    elif direction == 'right':
        position = start_position + pixels_per_second * t
        # Clamp the position to not exceed end_position
        clamped_position = min(end_position, position)
    
    # eZprint(f'panning {direction} to position {clamped_position}', ['OVERLAY'])
    return clamped_position

def count_time_passing():

    current_time = datetime.now()
    logger.debug(f'Current time: {current_time} - Last request time: {last_request_time}')
    difference = current_time - last_request_time
    logger.debug(f'Time difference: {difference}')

    return difference.total_seconds()


async def determine_orientation(clip_dimensions):
    
    # probe = ffmpeg.probe(video_file)
    # rotate_code = next((stream['tags']['rotate'] for stream in probe['streams'] if 'rotate' in stream['tags']), None)       
    # 

    print(f'clip dimensions: {clip_dimensions}')   

    if clip_dimensions[0] > clip_dimensions[1]:
        print('vertical clip' + str(clip_dimensions))
        return 'vertical'
    elif clip_dimensions[0] == clip_dimensions[1]:
        print('Square clip' + str(clip_dimensions))
        return 'square'
    else:
        print('Horizontal clip' + str(clip_dimensions))
        return 'horizontal'


async def is_rotated( file_path):
    rotation = await get_rotation(file_path)
    print('Rotation:', rotation)
    if rotation == 90:  # If video is in portrait
        return True
    elif rotation == -90:
        return True
    elif rotation == 270:  # Moviepy can only cope with 90, -90, and 180 degree turns
        return True
    elif rotation == -270:
        return True
    elif rotation == 180:
        return True
    elif rotation == -180:
        return True
    return False

async def get_rotation(source):
    # clip = VideoFileClip('IMG_3561.mov')
    cmd = "ffprobe -loglevel error -select_streams v:0 -show_entries side_data=rotation -of default=nw=1:nk=1 "
    args = shlex.split(cmd)
    args.append(source)
    print(args)
    logger.debug(f'Running ffprobe command: {args}')
    ffprobe_output = subprocess.check_output(args).decode('utf-8')
    # print(ffprobe_output)
    # split on return
    ffprobe_output = ffprobe_output.split('\n')
    logger.debug(f'ffprobe output: {ffprobe_output}')
    if ffprobe_output and len(ffprobe_output) > 0:  # Output of cmdis None if it should be 0
        # ffprobe_output = json.loads(ffprobe_output[0])
        rotation = int(ffprobe_output[0])
    else:
        rotation = 0

    # print(rotation)
    return rotation


