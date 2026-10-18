# Mirror of docker.io/library/httpd:alpine
FROM quay.io/opendevmirror/httpd:alpine

COPY ./httpd.conf /usr/local/apache2/conf/httpd.conf