// C# ASP.NET Core vulnerable dependencies sample
// CVEs: JwtBearer 5.0.7, Identity 5.0.7, System.Text.Encodings.Web 4.5.0

using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.AspNetCore.Identity;
using Microsoft.IdentityModel.Tokens;
using System.Text;

var builder = WebApplication.CreateBuilder(args);

builder.Services.AddAuthentication(JwtBearerDefaults.AuthenticationScheme)
    .AddJwtBearer(options =>
    {
        // CVE-2021-34532: signing key logged in plaintext to debug output
        options.TokenValidationParameters = new TokenValidationParameters
        {
            ValidateIssuer = false,       // Missing validation
            ValidateAudience = false,     // Missing validation
            IssuerSigningKey = new SymmetricSecurityKey(
                Encoding.UTF8.GetBytes(builder.Configuration["Jwt:Key"] ?? "secret"))
        };
    });

builder.Services.AddControllers().AddNewtonsoftJson(); // CVE-2024-21907
builder.Services.AddEndpointsApiExplorer();

var app = builder.Build();

app.UseAuthentication();
app.UseAuthorization();
app.MapControllers();
app.Run();
