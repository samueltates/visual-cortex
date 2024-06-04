import os
from quart import Quart, request, jsonify
from quart_cors import cors
import json
from media import overlay_b_roll, generate_b_roll
from transcribe import transcribe_file
from logger_manager import logger
from hypercorn.config import Config
import asyncio
from hypercorn.asyncio import serve

app = Quart(__name__)
app = cors(app, allow_origin=['*'], allow_headers=['content-type','Authorization'],  max_age=86400, allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
app.config['QUART_CORS_ALLOW_HEADERS'] = "contenttype, Authorization"
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024 * 100  # Setting the maximum request size to 100MB

@app.route('/')
def hello_world():
    return 'Hello, World!'

@app.route('/transform', methods=['POST'])
async def transform():
    logger.debug('Received a request to transform media')
    logger.debug(f'Payload details: {await request.get_json()}')

    try:
        payload = await request.get_json()
        aws_key = payload.get('aws_key')
        extension = payload.get('extension')
        b_roll_to_overlay = payload.get('b_roll_to_overlay')
        transcript_lines = payload.get('transcript_lines')

        logger.debug(f'Payload details: aws_key={aws_key}, extension={extension}, b_roll_to_overlay={b_roll_to_overlay}, transcript_lines={len(transcript_lines)} lines')

        transformed_media = await overlay_b_roll(aws_key, extension, b_roll_to_overlay, transcript_lines)
        logger.debug('Returning transformed media ')
        return jsonify(transformed_media)
    except Exception as e:
        logger.error(f'Error in transform endpoint: {str(e)}')
        return jsonify({'error': str(e)}), 500

@app.route('/handle_generate_b_roll', methods=['POST'])
async def handle_generate_b_roll():
    logger.debug('Received a request to generate b-roll')
    # logger.debug(f'Payload details: {await request.get_json()}')

    try:
        payload = await request.get_json()

        b_roll_with_sources = await generate_b_roll(payload)
        logger.debug('Returning transformed media ')
        return jsonify(b_roll_with_sources)

    except Exception as e:
        logger.error(f'Error in broll endpoint: {str(e)}')
        return jsonify({'error': str(e)}), 500
    
@app.route('/get_transcript', methods=['POST'])
async def get_transcript():
    payload = await request.get_json()

    logger.debug('Received request to get transcript with payload')
    file_key = payload.get('file_key')
    file_name = payload.get('file_name')
    file_type = payload.get('file_type')
    
    try:
        payload = await request.get_json()
        transcript_object = await transcribe_file(file_key, file_name, file_type)
        logger.debug('Returning transcript object ' )
        return jsonify(transcript_object)

    except Exception as e:
        logger.error(f'Error in transcript endpoint: {str(e)}')
        return jsonify({'error': str(e)}), 500

if __name__ =='__main__':
    host=os.getenv("HOST", default='0.0.0.0')
    port=int(os.getenv("PORT", default=5000))
    config = Config()
    config.bind = [str(host)+":"+str(port)]  # As an example configuration setting
    os.environ['AUTHLIB_INSECURE_TRANSPORT'] = '1'
    if os.getenv('ENVIRONMENT', default= 'production') == 'local':
        app.run(host=host, port=port)
        config.use_reloader = True
        config.debug = True
    else:
        asyncio.run(serve(app, config), debug=False)


    