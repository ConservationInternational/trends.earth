FROM boundlessgeo/qgis-testing-environment:master_2

WORKDIR /srv
RUN pip install pip==9.0.1
ADD ./requirements.txt /srv/requirements.txt
RUN pip install -r requirements.txt
ADD ./requirements-dev.txt /srv/requirements-dev.txt
RUN pip install -r requirements-dev.txt
