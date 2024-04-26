FROM --platform=linux/amd64 python:3.10

RUN mkdir -p /app
WORKDIR /app

COPY . .

ENV PIPENV_VENV_IN_PROJECT=1

RUN apt-get update && apt-get install ffmpeg libsm6 libxext6 fontconfig imagemagick -y

# Copy specific fonts into the container (if applicable)
COPY ./fonts /usr/share/fonts/truetype/myfonts
# Update font cache (if you copied fonts)
RUN fc-cache -fv

RUN pip install pipenv 
RUN pipenv sync

# RUN pipenv install --deploy --ignore-pipfile
RUN sed -i 's/none/read,write/g' /etc/ImageMagick-6/policy.xml

EXPOSE 5500

ENV NAME World

CMD [ "pipenv", "run", "python", "./app.py"]


