// The dashboard and launcher use the same reentrant, process-wide Windows mutex.
// OS ownership is released if a writer crashes.
#[cfg(windows)]
mod native {
    use std::ffi::c_void;
    #[link(name="kernel32")]
    extern "system" {
        fn CreateMutexW(attributes:*const c_void, owner:i32, name:*const u16)->*mut c_void;
        fn WaitForSingleObject(handle:*mut c_void, milliseconds:u32)->u32;
        fn ReleaseMutex(handle:*mut c_void)->i32;
        fn CloseHandle(handle:*mut c_void)->i32;
    }
    pub struct ConfigurationGuard(*mut c_void);
    impl ConfigurationGuard {
        pub fn acquire()->Result<Self,String> {
            let name:Vec<u16>="Local\\CCLauncherConfiguration\0".encode_utf16().collect();
            unsafe {let handle=CreateMutexW(std::ptr::null(),0,name.as_ptr());
                if handle.is_null(){return Err("无法锁定项目配置".into());}
                match WaitForSingleObject(handle,5000){0|0x80=>Ok(Self(handle)),_=>{CloseHandle(handle);Err("项目配置正在其他窗口保存，请稍后重试".into())}}
            }
        }
    }
    impl Drop for ConfigurationGuard {fn drop(&mut self){unsafe{ReleaseMutex(self.0);CloseHandle(self.0);}}}
}
#[cfg(windows)] pub use native::ConfigurationGuard;
#[cfg(not(windows))] pub struct ConfigurationGuard;
#[cfg(not(windows))] impl ConfigurationGuard {pub fn acquire()->Result<Self,String>{Ok(Self)}}

/// Replace only after a complete write, retaining the previous readable snapshot.
pub fn atomic_write(path:&std::path::Path,bytes:&[u8])->Result<(),String>{
    use std::io::Write;
    let temporary=path.with_extension(format!("{}.tmp",std::process::id()));
    let result=(||->Result<(),String>{
        let mut file=std::fs::File::create(&temporary).map_err(|e|e.to_string())?;
        file.write_all(bytes).map_err(|e|e.to_string())?;file.sync_all().map_err(|e|e.to_string())?;drop(file);
        if path.exists(){std::fs::copy(path,path.with_extension("json.bak")).map_err(|e|e.to_string())?;}
        #[cfg(windows)]{
            use std::os::windows::ffi::OsStrExt;
            #[link(name="kernel32")]extern "system"{fn MoveFileExW(from:*const u16,to:*const u16,flags:u32)->i32;}
            let from:Vec<u16>=temporary.as_os_str().encode_wide().chain(Some(0)).collect();let to:Vec<u16>=path.as_os_str().encode_wide().chain(Some(0)).collect();
            if unsafe{MoveFileExW(from.as_ptr(),to.as_ptr(),1|8)}==0{return Err(std::io::Error::last_os_error().to_string());}
        }
        #[cfg(not(windows))]std::fs::rename(&temporary,path).map_err(|e|e.to_string())?;
        Ok(())
    })();
    if temporary.exists(){let _=std::fs::remove_file(temporary);}result
}
