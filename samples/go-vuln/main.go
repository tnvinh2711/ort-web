package main

import (
	"fmt"
	"net/http"

	jwt "github.com/dgrijalva/jwt-go"
	"github.com/gorilla/websocket"
	"golang.org/x/crypto/ssh"
)

// CVE-2020-26160: jwt-go does not validate audience claim
func parseToken(tokenStr string) {
	token, _ := jwt.Parse(tokenStr, func(t *jwt.Token) (interface{}, error) {
		return []byte("secret"), nil
	})
	fmt.Println(token.Valid)
}

// CVE-2020-27813: integer overflow in gorilla/websocket
var upgrader = websocket.Upgrader{}

func wsHandler(w http.ResponseWriter, r *http.Request) {
	upgrader.Upgrade(w, r, nil)
}

// CVE-2020-29652: nil pointer in golang.org/x/crypto/ssh
func sshConnect(addr string, config *ssh.ClientConfig) {
	ssh.Dial("tcp", addr, config)
}

func main() {
	http.HandleFunc("/ws", wsHandler)
	http.ListenAndServe(":8080", nil)
}
