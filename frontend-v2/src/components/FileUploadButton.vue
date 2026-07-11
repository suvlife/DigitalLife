<script setup lang="ts">
import { ref } from 'vue';import * as api from '../api/client';
const props=defineProps<{roomId:number;disabled?:boolean}>();const emit=defineEmits<{uploaded:[name:string]}>();
const input=ref<HTMLInputElement|null>(null),uploading=ref(false),error=ref('');
const accept='.doc,.docx,.ppt,.pptx,.xls,.xlsx,.md,.markdown,.txt,.csv,.pdf';
async function choose(event:Event){const target=event.target as HTMLInputElement;const file=target.files?.[0];target.value='';if(!file)return;if(file.size>50*1024*1024){error.value='卷宗不得超过 50MB';return;}uploading.value=true;error.value='';try{await api.uploadFile(props.roomId,file);emit('uploaded',file.name);}catch(e){error.value=e instanceof Error?e.message:'卷宗上传失败';}finally{uploading.value=false;}}
</script>
<template><span class="room-file-upload"><button type="button" :disabled="disabled||uploading" @click="input?.click()">{{uploading?'正在递交卷宗…':'上传 Word / PPT / Excel / Markdown'}}</button><input ref="input" type="file" :accept="accept" hidden @change="choose"/><small v-if="error" class="error-text">{{error}}</small></span></template>
