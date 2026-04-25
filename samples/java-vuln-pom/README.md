# java-vuln-pom

Simple Maven project intentionally pinned to vulnerable dependencies for ORT/SCA testing.

## Vulnerable dependencies intentionally included

- `org.apache.logging.log4j:log4j-core:2.14.1`
- `com.fasterxml.jackson.core:jackson-databind:2.9.10.1`

## Build

```bash
mvn clean package
```

## Run

```bash
java -jar target/java-vuln-pom-1.0.0.jar
```
