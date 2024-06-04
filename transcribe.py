

import os
import tempfile
import asyncio
import json
import base64
import subprocess
from openai import OpenAI
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY', default=None))


from moviepy.editor import VideoFileClip
from pydub import AudioSegment
from pydub.silence import split_on_silence, detect_leading_silence, detect_nonsilent
from logger_manager import logger 

from s3 import read_file
# from tools.debug import eZprint

async def transcribe_file(file_key, file_name, file_type):
    # if not file_content:
    file_content = await read_file(file_key)
    processed_file = tempfile.NamedTemporaryFile(suffix=".mp4")
    processed_file.write(file_content)
    transcript_title = ''
    if 'video/' in file_type:
        print('video requested')
        logger.debug('video requested')
        transcript_title = await transcribe_video_file(processed_file, file_name)
    elif 'audio/' in file_type:
        logger.debug('audio requested')
        loop = asyncio.get_event_loop()
        audio = await loop.run_in_executor(None, lambda: AudioSegment.from_file(processed_file.name))
        # audio = await AudioSegment.from_file(processed_file.name)
        transcript_title = await transcribe_audio_file(audio, file_name)
        processed_file.close()
        

    else:
        transcript_title = "Unsupported file type for transcription"

    processed_file.close()
    return transcript_title


async def transcribe_video_file(file, name):
    clip = VideoFileClip(file.name)
    audio_temp = tempfile.NamedTemporaryFile( suffix=".mp3")
    clip.audio.write_audiofile(audio_temp.name)
    loop = asyncio.get_event_loop()
    audio = await loop.run_in_executor(None, lambda: AudioSegment.from_file(audio_temp.name))
    transcript_title = await transcribe_audio_file(audio, name)
    audio_temp.close()
    return transcript_title

async def transcribe_audio_file(audio, name):
    # eZprint(f"file to transcribe {file.name}", ['FILE_HANDLING', 'TRANSCRIBE'])
    # audio = AudioSegment.from_mp3(file.name)
    avg_loudness = audio.dBFS
    
    # Try reducing these values to create smaller clips
    silence_thresh = avg_loudness + (avg_loudness * 0.2)
    min_silence_len = 500
    logger.debug('seperating audio')

    # eZprint(f"silence thresh {silence_thresh} and min silence len {min_silence_len} from average loudness of {avg_loudness}", ['FILE_HANDLING', 'TRANSCRIBE'])
    # logger.debug(f"silence thresh {silence_thresh} and min silence len {min_silence_len} from average loudness of {avg_loudness}")


    chunk_loop = asyncio.get_event_loop()
    chunks = await chunk_loop.run_in_executor( None, lambda: split_on_silence(audio, min_silence_len=min_silence_len, silence_thresh=silence_thresh, keep_silence=True, seek_step=1))
    # split_on_silence(audio, min_silence_len=min_silence_len, silence_thresh=silence_thresh, keep_silence=True, seek_step=1)

    silence_loop = asyncio.get_event_loop()
    leading_silence = await silence_loop.run_in_executor(None, lambda: detect_leading_silence(audio, silence_threshold=silence_thresh, chunk_size=1))

    timestamp_loop = asyncio.get_event_loop()
    timestamps = await timestamp_loop.run_in_executor(None, lambda: detect_nonsilent(audio, min_silence_len=min_silence_len, silence_thresh=silence_thresh, seek_step=1))

    chunk_time_ms = 0
    transcript_text = f'\n{name} - Transcription: \n\n'

    chunk_time_ms = 0
    chunkID = 0
    tasks = []
    logger.debug(f'number of chunks is {len(chunks)}')
    for chunk in chunks:
        timestamp = timestamps[chunkID]

        if (os.getenv('DEBUG_TRANSCRIBE_NO_GAPS') == 'True'):
            start = chunk_time_ms
            end = chunk_time_ms + len(chunk)
            if chunkID == 0:
                start = int(leading_silence/ 2)
        elif (os.getenv('DEBUG_TRANSCRIBE_START_GAP') == 'True'):
            start = timestamp[0]
            end = chunk_time_ms + len(chunk)
        elif (os.getenv('DEBUG_TRANSCRIBE_START_END_GAP') == 'True'):
            start = timestamp[0]
            end = timestamp[1]
        else:
            ## currently my favourite, uses exact start, but clip end ...
            start = timestamp[0]
            end = chunk_time_ms + len(chunk)


        # if chunkID == len(chunks) - 1:
        task = asyncio.create_task(transcribe_chunk(chunk, start, end , chunkID))
        chunk_time_ms += len(chunk)
        
        tasks.append(task)
        chunkID += 1

    logger.debug('starting async gather transcribe chunks')
    results = await asyncio.gather(*tasks)
    results.sort(key=lambda x: x['chunkID'])
    end = ''
    transcript_text += f"[00:00:00.000] Start of clip \n\n"
    logger.debug('async gather complete')
    for result in results:
        # eZprint(f"chunk {result['chunkID']} start {result['start']} end {result['end']} text {result['text']}", ['FILE_HANDLING', 'TRANSCRIBE'])
        # logger.debug(f"chunk {chunkID} length {len(chunk)} and start time {timestamp[0]} and end time {timestamp[1] }")
        start = result['start']
        end = result['end']
        transcript_text += f"{start} --> {end}\n{result['text']} \n\n"
    # transcript text end time stap
    transcript_text += f"[{end}] End of clip \n\n"

    logger.debug(f'results combined, char length of transcript is {len(transcript_text)}')

    clip_length_in_seconds = len(audio) / 1000
    rounded_length = round(clip_length_in_seconds, 2)

    transcript_text +=  "\nTotal video clip length : " + str(rounded_length) + "s"

    transcript_object = {
                        'name' : name,
                        'description' : 'Transcription from ' + name,
                        'transcript_text' : transcript_text,
                        'lines' : results
                    }

    return transcript_object

async def transcribe_chunk(chunk, chunk_start, chunk_end, chunkID=0):
    with tempfile.NamedTemporaryFile(suffix='.mp3', delete=True) as chunk_file:
        chunk.export(chunk_file.name, format='mp3')
        # eZprint(f'Saved to:{chunk_file.name} with start of {chunk_start} and length of {chunk_end}', ['TRANSCRIBE_CHUNK'])  # Confirm file path
        # logger.debug(f'Saved to:{chunk_file.name} with start of {chunk_start} and length of {chunk_end}')
        # As the file is already created and written to disk, just use the file name.
        response = await asyncio.get_event_loop().run_in_executor(
            None, 
            lambda: client.audio.transcriptions.create(model='whisper-1', file=open(chunk_file.name, 'rb'))
        )
        # Make sure to close the file pointer inside the lambda function once done.

    chunk_file.close()
    start = await convert_ms_to_hh_mm_ss(chunk_start)
    end = await convert_ms_to_hh_mm_ss(chunk_end)
    if response:
        transcription = {
            'chunkID': chunkID,
            'start': start,
            'end': end,
            'text': response.text
        }
        # eZprint(f"chunk {chunkID} start {start} end {end} text {response.text}", ['FILE_HANDLING', 'TRANSCRIBE', 'DEBUG_TRANSCRIBE_CHUNK'])
        logger.debug(f"chunk {chunkID} start {start} end {end} text {response.text}")
        # write each audio chunk to temp folder as mp3 for analysis using time and transcript as title
        if os.getenv('DEBUG_TRANSCRIBE_CHUNK') == 'True':
            temp_chunk = tempfile.NamedTemporaryFile(suffix='.mp3', delete=False, prefix=f'{chunkID}_{start}_{end}_{response.text}')
            chunk.export(temp_chunk.name, format='mp3')
            temp_chunk.close()

        # os.remove(chunk_file.name)
        return transcription


async def convert_ms_to_hh_mm_ss(ms):
    seconds, ms = divmod(ms, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return ':'.join([str(hours).zfill(2), str(minutes).zfill(2), str(seconds).zfill(2)]) + '.' + str(ms).zfill(3) 


recordings = {}

async def setup_transcript_chunk(convoID, recordingID, chunkID, chunk):
    ## splitting here so can handle making spot for each chunk and returning before waiting for transcript so can get return response
    if not recordings.get(convoID):
        recordings[convoID] = {}
    if not recordings[convoID].get(recordingID):
        recordings[convoID][recordingID] = {}
    if not recordings[convoID][recordingID].get(chunkID):
        recordings[convoID][recordingID][chunkID] = {}

    recordings[convoID][recordingID][chunkID].update({
        'base64_data': chunk,
    })
    return
    

async def handle_transcript_chunk(convoID, recordingID, chunkID, chunk):
    # eZprint(f"trainscript chunk recording {recordingID} chunk {chunkID} length {len(chunk)}", ['FILE_HANDLING', 'TRANSCRIBE', 'TRANSCRIBE_CHUNK'])
    logger.debug(f"chunk {chunkID} text {transcript_text}")
    if not recordings.get(convoID):
        recordings[convoID] = {}
    if not recordings[convoID].get(recordingID):
        recordings[convoID][recordingID] = {}
    if not recordings[convoID][recordingID].get(chunkID):
        recordings[convoID][recordingID][chunkID] = {}

    decoded_chunk = base64.b64decode(chunk)
    transcript_text = await handle_simple_transcript(decoded_chunk)
    # eZprint(f"chunk {chunkID} text {transcript_text}", ['FILE_HANDLING', 'TRANSCRIBE', 'TRANSCRIBE_CHUNK'])
    logger.debug(f"chunk {chunkID} text {transcript_text}")
    if not recordings[convoID].get(recordingID):
        return
    recordings[convoID][recordingID][chunkID].update({
        'transcript_text': transcript_text
    })
    return transcript_text

async def handle_transcript_end(convoID, recordingID):
    if not recordings.get(convoID):
        return
    base64_chunks = []
    for chunk in recordings[convoID][recordingID].values():
        if chunk.get('base64_data'):
            base64_chunks.append(chunk['base64_data'])
    # eZprint(f"handle end recording {recordingID} chunks {len(base64_chunks)}", ['FILE_HANDLING', 'TRANSCRIBE', 'TRANSCRIBE_CHUNK'])
    logger.debug(f"handle end recording {recordingID} chunks {len(base64_chunks)}")
    combined_data = merge_and_decode_base64_chunks(base64_chunks)
    del recordings[convoID][recordingID]
    transcript_text = await handle_simple_transcript(combined_data, recordingID)
    return transcript_text


def merge_and_decode_base64_chunks(chunks):
    # Step 1: Concatenate all base64 chunks into one string
    decoded_chunks = [base64.b64decode(chunk) for chunk in chunks]

    # Step 2: Decode the base64 string into bytes
    combined_data = b"".join(decoded_chunks)

    # Step 3: Write the bytes into a wav file
    # with open('output-decode.webm', 'wb') as wav_file:
    #     wav_file.write(combined_data)

    return combined_data

async def handle_simple_transcript(audio_bytes, id = None):
    # Decode the base64 string to get the bytes

    # output_name = 'output-handle.webm'
    # if id:
    #     output_name = f'output-handle-{id}.webm'
    # with open(output_name, 'wb') as wav_file:

    #     wav_file.write(audio_bytes)

    # Use a temporary file to write the webm data
    with tempfile.NamedTemporaryFile(suffix='.webm') as tmp_webm_file:
        tmp_webm_file.write(audio_bytes)
        tmp_webm_file.close()  # Close the file so ffmpeg can read it

        # Convert WebM to WAV using ffmpeg
        tmp_wav_filename = os.path.splitext(tmp_webm_file.name)[0] + '.wav'
        conversion_command = [
            'ffmpeg',
            '-i', tmp_webm_file.name,
            '-vn',
            '-acodec', 'pcm_s16le',
            '-ar', '16000',
            '-ac', '1',
            tmp_wav_filename
        ]
        conversion_process = subprocess.run(
            conversion_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

        if conversion_process.returncode != 0:
            # Handle conversion error
            print(f"FFmpeg Error: {conversion_process.stderr}")
            return

        # At this point, tmp_wav_filename is the path to the WAV file
        # Now send the WAV file to OpenAI for transcription
        with open(tmp_wav_filename, 'rb') as audio_file:
            response = await asyncio.get_event_loop().run_in_executor(
                None, 
                lambda: client.audio.transcriptions.create(model='whisper-1', file=audio_file)
            )
        tmp_wav_filename.close()

        # Extract the transcript text from the response
        transcription = response.text
        # eZprint(f"chunk {chunkID} text {transcription}", ['FILE_HANDLING', 'TRANSCRIBE', 'TRANSCRIBE_CHUNK'])

    tmp_webm_file.close
    return transcription
