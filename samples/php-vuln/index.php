<?php
// PHP vulnerable dependencies sample
// CVE-2019-10913: Symfony routing RCE
// CVE-2022-31090: Guzzle header injection
// CVE-2020-36326: PHPMailer object injection

require 'vendor/autoload.php';

use GuzzleHttp\Client;

// CVE-2022-31090: Guzzle leaks Authorization header on redirect
$client = new Client(['allow_redirects' => true]);
$response = $client->get($_GET['url'] ?? 'https://example.com');
echo $response->getBody();
