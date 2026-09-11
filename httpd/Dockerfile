FROM httpd:2.4-alpine

RUN sed -i \
    -e 's/^#LoadModule proxy_module/LoadModule proxy_module/' \
    -e 's/^#LoadModule proxy_http_module/LoadModule proxy_http_module/' \
    /usr/local/apache2/conf/httpd.conf \
    && printf '\nServerName localhost\nInclude conf/extra/member-app.conf\n' >> /usr/local/apache2/conf/httpd.conf

COPY conf/member-app.conf /usr/local/apache2/conf/extra/member-app.conf
COPY htdocs/ /usr/local/apache2/htdocs/
