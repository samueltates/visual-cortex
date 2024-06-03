import logging

def setup_logger(name):
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    
    # Could further customize with handlers, formatters, etc.
    console_handler = logging.StreamHandler()
    # formatter = logging.Formatter('%(asctimes - %(name)s - %(levelname)s - %(message)s')
    # console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    return logger

logger = setup_logger(__name__)
