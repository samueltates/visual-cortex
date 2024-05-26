open -a Docker &
docker build -t visual-cortex . &
docker tag visual-cortex 914796322262.dkr.ecr.us-east-1.amazonaws.com/visual-cortex:latest &
aws configure sso --profile samazon &
aws ecr get-login-password --region us-east-1 --profile samazon | docker login --username AWS --password-stdin 914796322262.dkr.ecr.us-east-1.amazonaws.com & 
docker push 914796322262.dkr.ecr.us-east-1.amazonaws.com/visual-cortex

wait