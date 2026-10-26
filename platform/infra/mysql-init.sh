#!/bin/sh
set -eu
# Random passwords are hex; fail closed instead of interpolating arbitrary SQL.
case "$MYSQL_ANALYSIS_PASSWORD" in *[!a-f0-9]*|'') echo 'invalid generated read-only password' >&2; exit 1;; esac
MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --protocol=socket -uroot <<SQL
CREATE USER 'talent_readonly'@'%' IDENTIFIED BY '$MYSQL_ANALYSIS_PASSWORD';
-- Safe analytics view grants are installed after ORM initializes resources.
ALTER USER 'talent_readonly'@'%' WITH MAX_QUERIES_PER_HOUR 10000 MAX_USER_CONNECTIONS 5;
SQL

