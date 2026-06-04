// C++ vulnerable dependencies sample
// openssl/1.1.1s  — CVE-2022-4304 (timing attack), CVE-2023-0286 (use-after-free) CVSS 7.5
// libcurl/7.80.0  — CVE-2022-27774 (credential leak on redirect), CVE-2022-22576 (OAUTH2 reuse) CVSS 8.8
// zlib/1.2.12     — CVE-2022-37434 (heap buffer overflow) CVSS 9.8
// expat/2.4.1     — CVE-2022-25235, CVE-2022-25236, CVE-2022-25315 (XXE, integer overflow) CVSS 9.8

#include <curl/curl.h>
#include <openssl/ssl.h>
#include <openssl/err.h>
#include <zlib.h>
#include <expat.h>
#include <iostream>
#include <string>

// CVE-2022-27774: libcurl 7.80.0 leaks credentials on cross-protocol redirect
void fetch_url(const std::string& url) {
    CURL* curl = curl_easy_init();
    if (curl) {
        curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
        curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);
        curl_easy_setopt(curl, CURLOPT_USERPWD, "user:pass");
        curl_easy_perform(curl);
        curl_easy_cleanup(curl);
    }
}

// CVE-2022-37434: zlib 1.2.12 heap buffer overflow via malformed gzip input
void decompress(const char* input, int len) {
    z_stream zs{};
    inflateInit2(&zs, 16 + MAX_WBITS);
    zs.next_in  = (Bytef*)input;
    zs.avail_in = len;
    char out[4096];
    zs.next_out  = (Bytef*)out;
    zs.avail_out = sizeof(out);
    inflate(&zs, Z_FINISH);
    inflateEnd(&zs);
}

// CVE-2022-25235: expat 2.4.1 XML namespace injection via crafted XML
void parse_xml(const char* xml) {
    XML_Parser parser = XML_ParserCreate(nullptr);
    XML_Parse(parser, xml, strlen(xml), XML_TRUE);
    XML_ParserFree(parser);
}

int main() {
    SSL_library_init(); // openssl/1.1.1s — CVE-2022-4304 timing oracle
    fetch_url("http://example.com/resource");
    return 0;
}
