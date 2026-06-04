using Microsoft.AspNetCore.Mvc;
using Newtonsoft.Json;
using System.Net.Http;

namespace csharp_aspnet_vuln.Controllers;

[ApiController]
[Route("[controller]")]
public class UserController : ControllerBase
{
    private readonly HttpClient _http = new();

    // CVE-2018-8292: HttpClient leaks Authorization header on redirect
    [HttpGet("proxy")]
    public async Task<string> Proxy(string url)
    {
        _http.DefaultRequestHeaders.Add("Authorization", "Bearer " + Request.Headers["Authorization"]);
        return await _http.GetStringAsync(url);
    }

    // CVE-2024-21907: Newtonsoft.Json ReDoS via crafted JSON string
    [HttpPost("parse")]
    public IActionResult Parse([FromBody] string json)
    {
        var obj = JsonConvert.DeserializeObject(json);
        return Ok(JsonConvert.SerializeObject(obj));
    }
}
