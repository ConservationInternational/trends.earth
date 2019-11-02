FROM qgis/qgis:latest

RUN apt-get install unzip -y
RUN apt-get install wget -y

RUN pip3 install numba
RUN pip3 install invoke
RUN pip3 install boto3
RUN ln -s /usr/bin/pip3 /usr/bin/pip
