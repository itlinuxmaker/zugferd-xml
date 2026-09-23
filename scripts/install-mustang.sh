#!/bin/bash
# Builds a system-wide Mustang project with its own "mustang" command.

git clone https://github.com/ZUGFeRD/mustangproject.git /opt/mustangproject
cd /opt/mustangproject
./mvnw clean install
JAR=$(find /opt/mustangproject/Mustang-CLI/target -maxdepth 1 -type f -name 'Mustang-CLI-*.jar' | head -n 1)
ln -s "$JAR" /usr/local/lib/mustang.jar

cat > /usr/local/bin/mustang <<'EOF'
#!/bin/sh
exec java -jar /usr/local/lib/mustang.jar "$@"
EOF

chmod +x /usr/local/bin/mustang