module github.com/example/go-vuln-sample

go 1.19

require (
	// CVE-2020-29652 — nil pointer dereference / DoS in SSH
	golang.org/x/crypto v0.0.0-20200109152110-61a87790db17

	// CVE-2022-27664 — HTTP/2 DoS
	golang.org/x/net v0.0.0-20220425223048-2871e0cb64e4

	// CVE-2020-27813 — integer overflow in websocket
	github.com/gorilla/websocket v1.4.0

	// CVE-2020-26160 — jwt-go audience claim validation bypass
	github.com/dgrijalva/jwt-go v3.2.0+incompatible

	// CVE-2023-44487 — gRPC HTTP/2 rapid reset attack
	google.golang.org/grpc v1.50.0
)
