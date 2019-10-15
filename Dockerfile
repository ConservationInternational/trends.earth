FROM qgis/qgis:latest

RUN apt-get install unzip -y

WORKDIR /srv
ADD ./requirements-dev.txt /srv/requirements-dev.txt
RUN pip3 install numba
RUN pip3 install invoke
RUN pip3 install boto3
RUN pip3 install pytest
RUN pip3 install pytest-cov
RUN pip3 install coveralls
RUN ln -s /usr/bin/pip3 /usr/bin/pip
