// .NET vulnerable dependencies sample
// CVEs: Newtonsoft.Json 10.0.1, System.Net.Http 4.3.0,
//       System.Text.Encodings.Web 4.5.0, System.Security.Cryptography.Pkcs 6.0.0

using Newtonsoft.Json;
using System.Net.Http;

// CVE-2024-21907: ReDoS via crafted JSON
var obj = JsonConvert.DeserializeObject(Console.ReadLine() ?? "{}");
Console.WriteLine(JsonConvert.SerializeObject(obj));

// CVE-2018-8292: HttpClient leaks auth headers on redirect
using var client = new HttpClient();
var response = await client.GetAsync(args[0]);
Console.WriteLine(await response.Content.ReadAsStringAsync());
