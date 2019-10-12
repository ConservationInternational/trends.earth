FROM qgis/qgis:latest

WORKDIR /srv
ADD ./requirements-dev.txt /srv/requirements-dev.txt
RUN pip3 install numba
RUN pip3 install invoke
RUN pip3 install boto3
RUN ln -s /usr/bin/pip3 /usr/bin/pip
