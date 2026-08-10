const form=document.getElementById("registrationForm");const err=document.getElementById("error");
form.addEventListener("submit",e=>{e.preventDefault();err.classList.add("d-none");
const name=document.getElementById("name").value.trim(),mobile=document.getElementById("mobile").value.trim(),email=document.getElementById("email").value.trim(),instagram=document.getElementById("instagram").value.trim();
const competition=document.querySelector('input[name="competition"]:checked')?.value;const captured=document.querySelector('input[name="captured"]:checked')?.value;
if(!name||!/^\d{10}$/.test(mobile)||!email||!instagram||!competition||!captured){err.textContent="Please complete all fields correctly. Mobile number must be 10 digits.";err.classList.remove("d-none");return}
const id="GAC-"+Date.now().toString(36).toUpperCase();const data={id,name,mobile,email,instagram,competition,captured,status:"registered",createdAt:new Date().toISOString()};
localStorage.setItem("ganpati_registration",JSON.stringify(data));location.href="upload.html";});