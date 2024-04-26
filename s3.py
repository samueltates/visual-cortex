import os
import boto3
from logger_manager import logger

# from tools.debug import eZprint
s3 = boto3.client(
        's3',
        aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY')
    )

#log s3 status
from logger_manager import logger
# boto3.set_stream_logger('', logger.DEBUG)

async def write_file(file_content, file_name):

    # eZprint(f'Writing file {file_name}', ['AWS', 'FILE_HANDLING'])
    s3.put_object(Body=file_content, Bucket='ask-nova-media', Key=file_name)
    url = await get_signed_urls(file_name)
    # eZprint(f'File written to {url}', ['AWS', 'FILE_HANDLING'])
    return url

async def read_file(file_name):
    logger.debug(f'Reading file from S3: {file_name}')
    
    try:
        response = s3.get_object(Bucket='ask-nova-media', Key=file_name)
        file_content = response['Body'].read()
        logger.debug(f'Successfully read file {file_name} from S3')
        return file_content
    except Exception as e:
        logger.error(f'Error reading file {file_name} from S3: {str(e)}')
        raise e  # Rethrow the exception to handle it in the calling function.

async def get_signed_urls(file_name):
    presigned_url = s3.generate_presigned_url(
        'get_object', 
        Params={'Bucket': 'ask-nova-media', 'Key': file_name}, 
        ExpiresIn=3600)
    return presigned_url